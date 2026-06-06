"""Tests des API-Parsers für beide Antwortformate (smartTIMES & smartCONTROL).

Die erwarteten Preis-/Gebührenwerte sind die jeweils ersten Einträge der echten
API-Fixtures in ``tests/fixtures/`` – sie werden hier direkt gegen die Fixture
geprüft (nicht aus dem Parser-Code erzeugt) und im Kommentar mit ihrer Herkunft
dokumentiert.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.smartenergy.api import (
    MarketPrice,
    SmartTimesApiClient,
    SmartTimesApiError,
)


def _iso(value: str) -> datetime:
    """Kurzschreibweise für ein ISO-8601-datetime (mit Offset)."""
    return datetime.fromisoformat(value)


def test_parse_smarttimes(smarttimes_payload):
    """Das verschachtelte ``energyPrice``-Format wird vollständig ausgewertet."""
    result = SmartTimesApiClient._parse(smarttimes_payload)
    assert result.interval_minutes == 15
    assert result.unit == "cent/kWh"
    # Kein "tariff"-Feld im Payload -> dokumentierter Fallback.
    assert result.tariff == "smartTIMES"
    assert len(result.prices) == 192  # zwei Tage je 96 Viertelstunden
    # Chronologisch sortiert.
    assert result.prices == sorted(result.prices, key=lambda p: p.start)
    first = result.prices[0]
    # Erster Eintrag aus tests/fixtures/smarttimes.json (energyPrice.values[0]):
    # dateTimeFrom 2026-06-05T00:00:00+02:00, value 13.020.
    assert first.gross_ct_per_kwh == 13.020
    assert first.start == _iso("2026-06-05T00:00:00+02:00")
    assert first.end == _iso("2026-06-05T00:15:00+02:00")  # +15 min (interval)
    # Grundgebühr-Block (basicFee) wird ausgelesen.
    assert result.basic_fee_unit == "EUR/month"
    # Erster basicFee-Eintrag aus der Fixture (basicFee.values[0].value = 2.988).
    assert result.basic_fees[0].gross_value == 2.988


def test_parse_smartcontrol(smartcontrol_payload):
    """Das flache ``data``-Format (mit Offset) wird als Fallback ausgewertet."""
    result = SmartTimesApiClient._parse(smartcontrol_payload)
    assert result.interval_minutes == 15
    assert result.unit == "ct/kWh"
    assert result.tariff == "EPEXSPOTAT"
    assert len(result.prices) == 192
    # Erster Eintrag aus tests/fixtures/smartcontrol.json (data[0]):
    # date 2026-06-05T00:00:00+02:00, value 10.942.
    assert result.prices[0].gross_ct_per_kwh == 10.942
    assert result.prices[0].start == _iso("2026-06-05T00:00:00+02:00")
    # Kein basicFee-Block in dieser Antwort.
    assert result.basic_fees == []
    assert result.basic_fee_unit is None


def test_market_price_net_and_vat():
    """Brutto/Netto-Umrechnung: 13,020 brutto / 1,2 = 10,85 netto."""
    price = MarketPrice(
        start=_iso("2026-06-05T00:00:00+02:00"),
        end=_iso("2026-06-05T00:15:00+02:00"),
        gross_ct_per_kwh=13.020,
    )
    assert price.net_ct_per_kwh == 10.85
    assert price.price(include_vat=True) == 13.020
    assert price.price(include_vat=False) == 10.85


def test_parse_date_keeps_explicit_offset():
    """Ein vorhandener Zeitzonen-Offset bleibt erhalten (+02:00)."""
    parsed = SmartTimesApiClient._parse_date("2026-06-05T14:00:00+02:00")
    assert parsed.utcoffset().total_seconds() == 2 * 3600


def test_parse_date_assumes_default_tz_when_naive():
    """Ohne Offset wird die Standard-Zeitzone (Europe/Vienna) angenommen."""
    parsed = SmartTimesApiClient._parse_date("2026-06-05T14:00:00")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 2 * 3600


def test_parse_rejects_non_dict():
    """Ein nicht-Objekt als Antwort löst einen Fehler aus."""
    with pytest.raises(SmartTimesApiError):
        SmartTimesApiClient._parse([])


def test_parse_rejects_empty_values():
    """Eine leere Werteliste löst einen Fehler aus (keine Preisdaten)."""
    with pytest.raises(SmartTimesApiError):
        SmartTimesApiClient._parse({"energyPrice": {"values": []}})
