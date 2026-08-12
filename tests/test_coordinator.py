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
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient, SmartTimesApiError
from custom_components.smartenergy.const import (
    FETCH_FAILURE_REPAIR_HOURS,
    FETCH_JITTER_MINUTES,
    MIN_FETCH_INTERVAL_MINUTES,
    TARIFF_DATA_YEAR,
)
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
    entry_id: str | None = None,
) -> tuple[SmartTimesCoordinator, MagicMock]:
    """Baut einen Koordinator mit optional vorbefülltem Cache (Europe/Vienna)."""
    await hass.config.async_set_time_zone("Europe/Vienna")
    entry = MockConfigEntry(domain=DOMAIN, unique_id=entry_id or DOMAIN, entry_id=entry_id)
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
    coordinator._needs_fetch = lambda _: True  # Abruf erzwingen
    # Trotz Fehler bleiben die gecachten Daten erhalten (kein UpdateFailed).
    data = await coordinator._async_update_data()
    # 192 = 2 Tage (05.+06.06.2026) x 96 Viertelstunden/Tag (vgl. Modul-Docstring).
    assert len(data.prices) == 192


# --- Harte Untergrenze zwischen zwei API-Aufrufen ---------------------------- #


async def test_fetch_allowed_boundary(hass: HomeAssistant, smarttimes_payload):
    """Erst ``MIN_FETCH_INTERVAL_MINUTES`` nach dem letzten Versuch ist ein Abruf erlaubt."""
    coordinator, _ = await _coordinator(hass, smarttimes_payload)
    # Ohne vorherigen Versuch gibt es nichts zu bremsen.
    assert coordinator._fetch_allowed(datetime(2026, 6, 6, 18, 0, tzinfo=VIENNA)) is True

    coordinator._last_fetch = datetime(2026, 6, 6, 18, 0, tzinfo=VIENNA)
    threshold = coordinator._last_fetch + timedelta(minutes=MIN_FETCH_INTERVAL_MINUTES)
    assert coordinator._fetch_allowed(threshold - timedelta(seconds=1)) is False
    assert coordinator._fetch_allowed(threshold) is True


async def test_min_interval_blocks_refetch_despite_demand(
    hass: HomeAssistant, smarttimes_payload
):
    """Die Bremse verhindert den Abruf auch dann, wenn fachlich Bedarf bestünde.

    ``_needs_fetch`` wird hier auf „immer wahr" gesetzt – genau der Zustand, den
    ein künftiger Umbau versehentlich herstellen könnte. Die API darf trotzdem
    nicht angefragt werden, und die gecachten Preise bleiben erhalten.
    """
    coordinator, client = await _coordinator(hass, smarttimes_payload)
    client.async_get_prices = AsyncMock()
    coordinator._needs_fetch = lambda _: True
    coordinator._last_fetch = dt_util.now() - timedelta(minutes=1)

    data = await coordinator._async_update_data()

    client.async_get_prices.assert_not_called()
    # 192 = 2 Tage (05.+06.06.2026) x 96 Viertelstunden/Tag (vgl. Modul-Docstring).
    assert len(data.prices) == 192


async def test_min_interval_without_cache_reports_update_failed(hass: HomeAssistant):
    """Bremst die Wartezeit den Abruf, ohne dass je Daten vorlagen, meldet HA sauber.

    Grenzfall ohne Cache: Statt an einer Zusicherung zu scheitern, meldet der
    Koordinator ``UpdateFailed`` – Home Assistant wiederholt die Aktualisierung
    dann selbst.
    """
    coordinator, client = await _coordinator(hass)  # kein Cache
    client.async_get_prices = AsyncMock()
    coordinator._last_fetch = dt_util.now() - timedelta(minutes=1)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    client.async_get_prices.assert_not_called()


# --- Abruf-Jitter: deterministische Streuung über die Entry-ID --------------- #
#
# Geprüft werden – wie in test_jitter.py – **Invarianten**, kein nachgerechneter
# Hash. Zugesagt ist ein gleichverteilter Versatz über FETCH_JITTER_MINUTES
# Minuten, stabil je Installation.


@pytest.mark.parametrize(
    "entry_id", ["a", "smartenergy", "01JQZX7P8N4M2K6R", "0" * 32, "üü-ß"]
)
async def test_fetch_jitter_within_window(hass: HomeAssistant, entry_id):
    """Der Versatz liegt stets im Fenster 0..FETCH_JITTER_MINUTES-1 Minuten."""
    coordinator, _ = await _coordinator(hass, entry_id=entry_id)
    assert 0 <= coordinator._jitter_minutes <= FETCH_JITTER_MINUTES - 1


async def test_fetch_jitter_is_deterministic(hass: HomeAssistant):
    """Dieselbe Entry-ID ergibt denselben Versatz – auch über einen Reload hinweg."""
    first, _ = await _coordinator(hass, entry_id="01JQZX7P8N4M2K6R")
    second, _ = await _coordinator(hass, entry_id="01JQZX7P8N4M2K6R")
    assert first._jitter_minutes == second._jitter_minutes


async def test_fetch_jitter_spreads_across_entries(hass: HomeAssistant):
    """Verschiedene Entry-IDs verteilen sich über das Abruf-Fenster.

    Bei Gleichverteilung über 20 Minuten sind aus 40 IDs rund 17 verschiedene
    Werte zu erwarten. Geprüft wird nur die deutlich lockerere Schranke „mindestens
    die Hälfte der Minuten belegt", damit der Test die Streuung nachweist, ohne
    an einem konkreten Hash-Verfahren zu kleben.
    """
    values = {
        (await _coordinator(hass, entry_id=f"entry-{index:03d}"))[0]._jitter_minutes
        for index in range(40)
    }
    assert len(values) >= FETCH_JITTER_MINUTES // 2


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
    hass: HomeAssistant, smarttimes_payload, freezer
):
    """Ein dauerhafter Abruf-Fehler meldet ein Issue, das bei Erfolg wieder schließt."""
    await hass.config.async_set_time_zone("Europe/Vienna")
    coordinator, client = await _coordinator(hass, smarttimes_payload)
    coordinator._needs_fetch = lambda _: True  # Abruf-Versuch erzwingen
    # Letzter Erfolg liegt länger als FETCH_FAILURE_REPAIR_HOURS zurück.
    coordinator._last_success = datetime(2026, 6, 5, 0, 0, tzinfo=VIENNA)
    client.async_get_prices = AsyncMock(side_effect=SmartTimesApiError("boom"))

    await coordinator._async_update_data()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_FETCH_FAILING)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING

    # Der nächste Abruf gelingt wieder -> Issue schließt sich automatisch.
    # Dafür muss die Uhr weiterlaufen: Zwei echte Abrufe liegen nie im selben
    # Augenblick, dazwischen liegt mindestens die Wiederholungs-Wartezeit
    # (siehe _fetch_allowed / MIN_FETCH_INTERVAL_MINUTES).
    freezer.move_to("2026-06-08 12:30:00")
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
