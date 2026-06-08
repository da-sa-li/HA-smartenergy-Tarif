"""Tests des Koordinators: Abruf-Drosselung (``_needs_fetch``) und Cache-Verhalten.

Die Drosselung ist rein zeitabhängig und daher ohne eingefrorene Uhr kaum
testbar – hier wird der maßgebliche Zeitpunkt direkt an ``_needs_fetch``
übergeben. Bezugsdaten: die smartTIMES-Fixture deckt den 05.06. und 06.06.2026 ab
(letztes Intervall endet 07.06. 00:00).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient, SmartTimesApiError
from custom_components.smartenergy.const import FETCH_FAILURE_REPAIR_HOURS, TARIFF_DATA_YEAR
from custom_components.smartenergy.coordinator import SmartTimesCoordinator
from custom_components.smartenergy.repairs import (
    ISSUE_FETCH_FAILING,
    ISSUE_TARIFF_DATA_OUTDATED,
)
from tests.conftest import VIENNA

DOMAIN = "smartenergy"


async def _coordinator(
    hass: HomeAssistant,
    payload: dict | None = None,
    *,
    last_fetch: datetime | None = None,
) -> tuple[SmartTimesCoordinator, MagicMock]:
    """Baut einen Koordinator mit optional vorbefülltem Cache (Europe/Vienna)."""
    await hass.config.async_set_time_zone("Europe/Vienna")
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    client = MagicMock()
    coordinator = SmartTimesCoordinator(hass, entry, client, include_vat=True)
    if payload is not None:
        coordinator._last_result = SmartTimesApiClient._parse(payload)
    coordinator._last_fetch = last_fetch
    return coordinator, client


async def test_needs_fetch_without_cache(hass: HomeAssistant):
    """Ohne Cache wird immer abgerufen."""
    coordinator, _ = await _coordinator(hass)
    assert coordinator._needs_fetch(datetime(2026, 6, 5, 12, 0, tzinfo=VIENNA)) is True


async def test_no_fetch_when_tomorrow_present(hass: HomeAssistant, smarttimes_payload):
    """Sind die Morgen-Preise bereits im Cache, wird nicht abgerufen."""
    coordinator, _ = await _coordinator(hass, smarttimes_payload)
    # now am 05.06. -> morgen (06.06.) ist enthalten -> kein Abruf.
    assert coordinator._needs_fetch(datetime(2026, 6, 5, 12, 0, tzinfo=VIENNA)) is False


async def test_no_fetch_before_threshold_hour(hass: HomeAssistant, smarttimes_payload):
    """Vor NEXT_DAY_PRICES_HOUR wird trotz fehlender Morgen-Preise nicht abgerufen."""
    coordinator, _ = await _coordinator(hass, smarttimes_payload)
    # now am 06.06. 12:00 -> morgen (07.06.) fehlt, aber vor 17:00 -> kein Abruf.
    assert coordinator._needs_fetch(datetime(2026, 6, 6, 12, 0, tzinfo=VIENNA)) is False


async def test_fetch_after_threshold_when_tomorrow_missing(
    hass: HomeAssistant, smarttimes_payload
):
    """Nach der Schwellenstunde wird abgerufen, wenn die Morgen-Preise fehlen."""
    coordinator, _ = await _coordinator(hass, smarttimes_payload, last_fetch=None)
    # 06.06. 18:00 -> nach 17:00+Jitter, morgen fehlt, noch nie geholt -> Abruf.
    assert coordinator._needs_fetch(datetime(2026, 6, 6, 18, 0, tzinfo=VIENNA)) is True


async def test_no_fetch_after_threshold_if_recently_fetched(
    hass: HomeAssistant, smarttimes_payload
):
    """Innerhalb des Retry-Intervalls wird nicht erneut abgerufen."""
    coordinator, _ = await _coordinator(
        hass, smarttimes_payload, last_fetch=datetime(2026, 6, 6, 17, 50, tzinfo=VIENNA)
    )
    # 10 min nach letztem Versuch (< 30 min Retry-Intervall) -> kein Abruf.
    assert coordinator._needs_fetch(datetime(2026, 6, 6, 18, 0, tzinfo=VIENNA)) is False


async def test_fetch_when_cache_expired(hass: HomeAssistant, smarttimes_payload):
    """Deckt der Cache den aktuellen Zeitpunkt nicht mehr ab, wird abgerufen."""
    coordinator, _ = await _coordinator(hass, smarttimes_payload, last_fetch=None)
    # now nach dem letzten gecachten Intervall -> Abruf (Cache deckt nicht ab).
    assert coordinator._needs_fetch(datetime(2026, 6, 10, 12, 0, tzinfo=VIENNA)) is True


async def test_first_fetch_failure_raises_update_failed(hass: HomeAssistant):
    """Schlägt der allererste Abruf fehl, wird UpdateFailed ausgelöst."""
    coordinator, client = await _coordinator(hass)  # kein Cache
    client.async_get_prices = AsyncMock(side_effect=SmartTimesApiError("boom"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_fetch_failure_keeps_cached_data(
    hass: HomeAssistant, smarttimes_payload
):
    """Bei einem Abruf-Fehler mit vorhandenem Cache bleiben die Daten erhalten."""
    coordinator, client = await _coordinator(hass, smarttimes_payload)
    client.async_get_prices = AsyncMock(side_effect=SmartTimesApiError("boom"))
    coordinator._needs_fetch = lambda now: True  # Abruf erzwingen
    # Trotz Fehler bleiben die gecachten Daten erhalten (kein UpdateFailed).
    data = await coordinator._async_update_data()
    # 192 = 2 Tage (05.+06.06.2026) x 96 Viertelstunden/Tag (vgl. Modul-Docstring).
    assert len(data.prices) == 192


# --- Repair-Issues (Issue #36): dauerhafter Abruf-Fehler / veraltete Tarifdaten -- #


async def test_fetch_not_failing_without_prior_success(hass: HomeAssistant):
    """Ohne je gelungenen Abruf gilt der Cache (noch) nicht als dauerhaft veraltet.

    Praktisch unerreichbar von außen (ein erster Fehlschlag löst ``UpdateFailed``
    aus, bevor die Prüfung greift), dokumentiert aber die Grenzbedingung von
    ``_fetch_failing``.
    """
    coordinator, _ = await _coordinator(hass)
    assert coordinator._fetch_failing(datetime(2026, 6, 5, 12, 0, tzinfo=VIENNA)) is False


async def test_fetch_failing_threshold(hass: HomeAssistant, smarttimes_payload):
    """Erst ab ``FETCH_FAILURE_REPAIR_HOURS`` ohne Erfolg gilt der Abruf als gestört."""
    coordinator, _ = await _coordinator(hass, smarttimes_payload)
    coordinator._last_success = datetime(2026, 6, 5, 0, 0, tzinfo=VIENNA)
    threshold = coordinator._last_success + timedelta(hours=FETCH_FAILURE_REPAIR_HOURS)

    assert coordinator._fetch_failing(threshold - timedelta(minutes=1)) is False
    assert coordinator._fetch_failing(threshold) is True


@pytest.mark.freeze_time("2026-06-08 12:00:00")
async def test_persistent_fetch_failure_reports_and_clears_repair_issue(
    hass: HomeAssistant, smarttimes_payload
):
    """Ein dauerhafter Abruf-Fehler meldet ein Issue, das bei Erfolg wieder schließt."""
    await hass.config.async_set_time_zone("Europe/Vienna")
    coordinator, client = await _coordinator(hass, smarttimes_payload)
    coordinator._needs_fetch = lambda now: True  # Abruf-Versuch erzwingen
    # Letzter Erfolg liegt länger als FETCH_FAILURE_REPAIR_HOURS zurück.
    coordinator._last_success = datetime(2026, 6, 5, 0, 0, tzinfo=VIENNA)
    client.async_get_prices = AsyncMock(side_effect=SmartTimesApiError("boom"))

    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_FETCH_FAILING)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING

    # Der nächste Abruf gelingt wieder -> Issue schließt sich automatisch.
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    client.async_get_prices = AsyncMock(return_value=parsed)
    await coordinator._async_update_data()

    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_FETCH_FAILING) is None


@pytest.mark.freeze_time("2027-01-02 12:00:00")
async def test_outdated_tariff_data_year_reports_repair_issue(
    hass: HomeAssistant, smarttimes_payload
):
    """Liegt das laufende Jahr nach ``TARIFF_DATA_YEAR``, entsteht das Daten-Issue.

    2027 > TARIFF_DATA_YEAR (2026) – die in ``grid_fees.py``/``surcharges.py``
    hinterlegten "Stand 2026"-Sätze gelten dann als veraltet (Spezifikation aus
    Issue #36: "wenn das aktuelle Jahr größer ist als das Jahr der hinterlegten
    Netzentgelte").
    """
    assert TARIFF_DATA_YEAR == 2026
    await hass.config.async_set_time_zone("Europe/Vienna")
    coordinator, client = await _coordinator(hass)  # kein Cache -> erster Abruf
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    client.async_get_prices = AsyncMock(return_value=parsed)

    await coordinator._async_update_data()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_TARIFF_DATA_OUTDATED)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {"data_year": str(TARIFF_DATA_YEAR)}
