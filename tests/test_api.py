"""Tests des API-Parsers für beide Antwortformate (smartTIMES & smartCONTROL)."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.smartenergy.api import (
    MarketPrice,
    SmartTimesApiClient,
    SmartTimesApiError,
)


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_parse_smarttimes(smarttimes_payload):
    result = SmartTimesApiClient._parse(smarttimes_payload)
    assert result.interval_minutes == 15
    assert result.unit == "cent/kWh"
    # Kein "tariff"-Feld im Payload -> dokumentierter Fallback.
    assert result.tariff == "smartTIMES"
    assert len(result.prices) == 192  # zwei Tage je 96 Viertelstunden
    # Chronologisch sortiert.
    assert result.prices == sorted(result.prices, key=lambda p: p.start)
    first = result.prices[0]
    assert first.gross_ct_per_kwh == 13.020
    assert first.start == _iso("2026-06-05T00:00:00+02:00")
    assert first.end == _iso("2026-06-05T00:15:00+02:00")
    # Grundgebühr-Block (basicFee) wird ausgelesen.
    assert result.basic_fee_unit == "EUR/month"
    assert result.basic_fees[0].gross_value == 2.988


def test_parse_smartcontrol(smartcontrol_payload):
    result = SmartTimesApiClient._parse(smartcontrol_payload)
    assert result.interval_minutes == 15
    assert result.unit == "ct/kWh"
    assert result.tariff == "EPEXSPOTAT"
    assert len(result.prices) == 192
    assert result.prices[0].gross_ct_per_kwh == 10.942
    assert result.prices[0].start == _iso("2026-06-05T00:00:00+02:00")
    # Kein basicFee-Block in dieser Antwort.
    assert result.basic_fees == []
    assert result.basic_fee_unit is None


def test_market_price_net_and_vat():
    # 13,020 brutto / 1,2 = 10,85 netto.
    price = MarketPrice(
        start=_iso("2026-06-05T00:00:00+02:00"),
        end=_iso("2026-06-05T00:15:00+02:00"),
        gross_ct_per_kwh=13.020,
    )
    assert price.net_ct_per_kwh == 10.85
    assert price.price(include_vat=True) == 13.020
    assert price.price(include_vat=False) == 10.85


def test_parse_date_keeps_explicit_offset():
    parsed = SmartTimesApiClient._parse_date("2026-06-05T14:00:00+02:00")
    assert parsed.utcoffset().total_seconds() == 2 * 3600


def test_parse_date_assumes_default_tz_when_naive():
    # Ohne Offset -> Europe/Vienna (Standard-Zeitzone aus der Fixture).
    parsed = SmartTimesApiClient._parse_date("2026-06-05T14:00:00")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 2 * 3600


def test_parse_rejects_non_dict():
    with pytest.raises(SmartTimesApiError):
        SmartTimesApiClient._parse([])


def test_parse_rejects_empty_values():
    with pytest.raises(SmartTimesApiError):
        SmartTimesApiClient._parse({"energyPrice": {"values": []}})
