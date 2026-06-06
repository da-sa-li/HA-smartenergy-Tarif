"""Tests des Koordinators: Abruf-Drosselung (``_needs_fetch``) und Cache-Verhalten.

Die Drosselung ist rein zeitabhängig und daher ohne eingefrorene Uhr kaum
testbar – hier wird der maßgebliche Zeitpunkt direkt an ``_needs_fetch``
übergeben. Bezugsdaten: die smartTIMES-Fixture deckt den 05.06. und 06.06.2026 ab
(letztes Intervall endet 07.06. 00:00).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient, SmartTimesApiError
from custom_components.smartenergy.coordinator import SmartTimesCoordinator
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
