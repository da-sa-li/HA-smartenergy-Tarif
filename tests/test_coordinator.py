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

from custom_components.smartenergy.api import (
    SmartTimesApiClient,
    SmartTimesApiError,
    SmartTimesApiPermanentError,
)
from custom_components.smartenergy.const import (
    FETCH_FAILURE_REPAIR_HOURS,
    FETCH_JITTER_MINUTES,
    FETCH_RETRY_MAX_INTERVAL_MINUTES,
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


# --- Wachsende Wartezeit zwischen Wiederholungsversuchen --------------------- #


async def test_retry_delay_grows_and_caps(hass: HomeAssistant, smarttimes_payload):
    """Die Wartezeit wächst je erfolglosem Versuch bis zur Obergrenze.

    Sollwerte von Hand aus der Spezifikation abgeleitet: Basis 30 Minuten, ab dem
    *zweiten* erfolglosen Versuch Verdopplung, Deckel 120 Minuten. Für die Zähler
    0..5 ergibt das 30, 30, 60, 120, 120, 120.
    """
    coordinator, _ = await _coordinator(hass, smarttimes_payload)
    for failures, minutes in enumerate([30, 30, 60, 120, 120, 120]):
        coordinator._failed_attempts = failures
        assert coordinator._retry_delay() == timedelta(minutes=minutes)


async def test_retry_after_extends_but_never_shortens(
    hass: HomeAssistant, smarttimes_payload
):
    """``Retry-After`` verlängert die Wartezeit, verkürzt sie aber nie."""
    coordinator, _ = await _coordinator(hass, smarttimes_payload)
    coordinator._failed_attempts = 1  # eigene Wartezeit: 30 Minuten

    coordinator._retry_after = timedelta(minutes=90)
    assert coordinator._retry_delay() == timedelta(minutes=90)

    coordinator._retry_after = timedelta(minutes=5)
    assert coordinator._retry_delay() == timedelta(minutes=30)


async def test_failures_count_up(hass: HomeAssistant, smarttimes_payload):
    """Jeder fehlgeschlagene Abruf erhöht den Zähler und damit die Wartezeit."""
    coordinator, client = await _coordinator(hass, smarttimes_payload)
    client.async_get_prices = AsyncMock(side_effect=SmartTimesApiError("boom"))
    coordinator._needs_fetch = lambda _: True

    await coordinator._async_update_data()
    assert coordinator._failed_attempts == 1
    assert coordinator._retry_delay() == timedelta(minutes=30)

    coordinator._last_fetch = None  # Mindestwartezeit für den Test umgehen
    await coordinator._async_update_data()
    assert coordinator._failed_attempts == 2
    assert coordinator._retry_delay() == timedelta(minutes=60)


async def test_permanent_error_jumps_to_max_interval(
    hass: HomeAssistant, smarttimes_payload
):
    """Eine dauerhafte Ablehnung wartet sofort das Maximal-Intervall ab.

    Sich vom Basis-Intervall dorthin hochzuzählen brächte nichts: Ein 404 oder
    403 verschwindet durch rasches Wiederholen nicht.
    """
    coordinator, client = await _coordinator(hass, smarttimes_payload)
    client.async_get_prices = AsyncMock(
        side_effect=SmartTimesApiPermanentError("HTTP 404")
    )
    coordinator._needs_fetch = lambda _: True

    await coordinator._async_update_data()

    assert coordinator._retry_delay() == timedelta(
        minutes=FETCH_RETRY_MAX_INTERVAL_MINUTES
    )


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit, vor 17 Uhr
async def test_successful_fetch_resets_backoff(
    hass: HomeAssistant, smarttimes_payload
):
    """Ein gelungener Abruf setzt Zähler und ``Retry-After`` zurück."""
    coordinator, client = await _coordinator(hass, smarttimes_payload)
    coordinator._failed_attempts = 3
    coordinator._retry_after = timedelta(minutes=90)
    coordinator._needs_fetch = lambda _: True
    client.async_get_prices = AsyncMock(
        return_value=SmartTimesApiClient._parse(smarttimes_payload)
    )

    await coordinator._async_update_data()

    assert coordinator._failed_attempts == 0
    assert coordinator._retry_after is None
    assert coordinator._retry_delay() == timedelta(minutes=30)


@pytest.mark.freeze_time("2026-06-06 16:00:00")  # 18:00 Ortszeit, nach 17 Uhr
async def test_successful_fetch_without_tomorrow_prices_backs_off(
    hass: HomeAssistant, smarttimes_payload
):
    """Fehlen die Morgen-Preise trotz gelungenem Abruf, wächst die Wartezeit.

    Die Fixture deckt den 05. und 06.06.2026 ab. Um 18:00 Ortszeit am 06.06.
    sollten die Preise für den 07.06. laut API-Zeitplan (17 Uhr) vorliegen – sie
    fehlen aber. Genau dieser Fall erzeugte bisher bis in die Nacht hinein alle
    30 Minuten einen Abruf.
    """
    coordinator, client = await _coordinator(hass, smarttimes_payload)
    coordinator._needs_fetch = lambda _: True
    client.async_get_prices = AsyncMock(
        return_value=SmartTimesApiClient._parse(smarttimes_payload)
    )

    await coordinator._async_update_data()

    assert coordinator._failed_attempts == 1


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

    ``_needs_fetch`` wird hier auf „immer wahr“ gesetzt – genau der Zustand, den
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


# --- Abruf-Jitter: Streuung über Entry-ID und Kalendertag -------------------- #
#
# Geprüft werden – wie in test_jitter.py – **Invarianten**, kein nachgerechneter
# Hash. Zugesagt ist ein gleichverteilter Versatz über FETCH_JITTER_MINUTES
# Minuten, innerhalb eines Tages konstant und von Tag zu Tag wechselnd.

JITTER_DAY = datetime(2026, 6, 5, 12, 0, tzinfo=VIENNA)


@pytest.mark.parametrize(
    "entry_id", ["a", "smartenergy", "01JQZX7P8N4M2K6R", "0" * 32, "üü-ß"]
)
async def test_fetch_jitter_within_window(hass: HomeAssistant, entry_id):
    """Der Versatz liegt stets im Fenster 0..FETCH_JITTER_MINUTES-1 Minuten."""
    coordinator, _ = await _coordinator(hass, entry_id=entry_id)
    assert 0 <= coordinator._jitter_minutes(JITTER_DAY) <= FETCH_JITTER_MINUTES - 1


async def test_fetch_jitter_is_stable_within_a_day(hass: HomeAssistant):
    """Über einen Tag hinweg bleibt der Versatz konstant.

    Der Koordinator rechnet minütlich neu; ein wandernder Versatz würde die
    Abruf-Schwelle ständig verschieben und den Abruf faktisch auf die früheste
    Minute des Fensters ziehen.
    """
    coordinator, _ = await _coordinator(hass, entry_id="01JQZX7P8N4M2K6R")
    morning = coordinator._jitter_minutes(datetime(2026, 6, 5, 0, 1, tzinfo=VIENNA))
    evening = coordinator._jitter_minutes(datetime(2026, 6, 5, 23, 59, tzinfo=VIENNA))
    assert morning == evening


async def test_fetch_jitter_is_reproducible_across_reloads(hass: HomeAssistant):
    """Dieselbe Entry-ID ergibt am selben Tag denselben Versatz."""
    first, _ = await _coordinator(hass, entry_id="01JQZX7P8N4M2K6R")
    second, _ = await _coordinator(hass, entry_id="01JQZX7P8N4M2K6R")
    assert first._jitter_minutes(JITTER_DAY) == second._jitter_minutes(JITTER_DAY)


async def test_fetch_jitter_changes_across_days(hass: HomeAssistant):
    """Der Versatz wechselt über die Tage – kein dauerhaft wiedererkennbares Muster.

    Ein über Jahre gleichbleibender Versatz wäre gegenüber dem API-Betreiber ein
    langlebiges Zeitmuster. Geprüft wird über 30 aufeinanderfolgende Tage: Bei
    einem festen Versatz gäbe es genau einen Wert; erwartet werden bei
    Gleichverteilung über 20 Minuten rund 15 verschiedene.
    """
    coordinator, _ = await _coordinator(hass, entry_id="01JQZX7P8N4M2K6R")
    values = {
        coordinator._jitter_minutes(JITTER_DAY + timedelta(days=offset))
        for offset in range(30)
    }
    assert len(values) >= FETCH_JITTER_MINUTES // 2


async def test_fetch_jitter_spreads_across_entries(hass: HomeAssistant):
    """Verschiedene Entry-IDs verteilen sich am selben Tag über das Abruf-Fenster.

    Bei Gleichverteilung über 20 Minuten sind aus 40 IDs rund 17 verschiedene
    Werte zu erwarten. Geprüft wird nur die deutlich lockerere Schranke „mindestens
    die Hälfte der Minuten belegt“, damit der Test die Streuung nachweist, ohne
    an einem konkreten Hash-Verfahren zu kleben.
    """
    values = {
        (await _coordinator(hass, entry_id=f"entry-{index:03d}"))[0]._jitter_minutes(
            JITTER_DAY
        )
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
    coordinator, client = await _coordinator(hass)  # kein Cache -> erster Abruf
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    client.async_get_prices = AsyncMock(return_value=parsed)

    await coordinator._async_update_data()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_TARIFF_DATA_OUTDATED)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {"data_year": str(TARIFF_DATA_YEAR)}
