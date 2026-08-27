"""Tests des Schaltverhaltens über die Zeit – an der laufenden HA-Instanz.

Alle übrigen HA-Tests dieser Suite prüfen **einen eingefrorenen Augenblick**:
Sie richten den Eintrag ein und lesen den Zustand einmal ab. Die Uhr wird dabei
nie weitergedreht, ``async_fire_time_changed`` kam in der Suite bislang gar
nicht vor. Damit war die zentrale Zusage der Integration ungeprüft – nämlich
dass der Günstige-Stunde-Sensor an der **gejitterten** Blockkante ein- und
ausschaltet und die Preissensoren dem Intervallwechsel folgen.

Die Rechnung dahinter (``is_cheap_now``, ``jittered_window``) ist als reine
Funktion gut abgedeckt; hier geht es um die Kette darüber: Der Koordinator muss
minütlich neu rechnen und die Entitäten müssen den neuen Stand übernehmen.

Sollwerte von Hand, smartTIMES + Netzgebiet Wien, cheap_hours = 4,0,
exact_hours = ein (Herleitung der Preisstufen siehe Kopf des Zeitstempel-
Abschnitts in ``tests/test_sensor.py``): Günstig ist der Block **10:00-14:00**
Ortszeit an beiden Fixture-Tagen.

Mit der Fixture ``ohne_jitter`` (Phase 0) liegt das Schaltfenster damit auf
**10:00:00 bis 13:50:00** – die Ausschaltflanke wird um die volle Jitterbreite
``JITTER_SPAN_SECONDS`` (600 s) vorgezogen, die Einschaltflanke bei Phase 0 gar
nicht verzögert. Genau das ist die Zusage „beide Flanken wandern nach innen“,
hier am Sensor gemessen statt an der Hilfsfunktion.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.const import JITTER_SPAN_SECONDS
from tests.conftest import VIENNA

DOMAIN = "smartenergy"

GUENSTIG_SENSOR = "binary_sensor.boiler_cheap_hour"
ARBEITSPREIS_SENSOR = "sensor.smarttimes_strompreishelfer_energy_price"
NAECHSTER_START_SENSOR = "sensor.boiler_next_cheap_start"

BLOCK_BEGINN = datetime(2026, 6, 5, 10, 0, tzinfo=VIENNA)
BLOCK_ENDE = datetime(2026, 6, 5, 14, 0, tzinfo=VIENNA)
# Ausschaltflanke bei Phase 0: um die volle Jitterbreite vorgezogen.
AUS_OHNE_JITTER = BLOCK_ENDE - timedelta(seconds=JITTER_SPAN_SECONDS)


def _lokal(text: str) -> datetime:
    """Kurzschreibweise für einen Zeitpunkt am 05.06.2026 in Wiener Ortszeit."""
    stunde, minute = (int(teil) for teil in text.split(":"))
    return datetime(2026, 6, 5, stunde, minute, tzinfo=VIENNA)


class _Uhr:
    """Richtet einen Eintrag ein und dreht danach die Uhr der HA-Instanz weiter.

    Der API-Abruf bleibt über die gesamte Lebensdauer gepatcht: Wird die Uhr
    über die Schwellenstunde oder über das Ende der gecachten Preise hinaus
    gedreht, will der Koordinator neu abrufen – ohne den Patch ginge das gegen
    die (gesperrte) echte Verbindung.
    """

    def __init__(self, hass: HomeAssistant, freezer) -> None:
        """Merkt sich die HA-Instanz und die eingefrorene Uhr."""
        self._hass = hass
        self._freezer = freezer

    async def vorspulen(self, moment: datetime) -> None:
        """Stellt die Uhr auf ``moment`` und lässt Home Assistant nachziehen."""
        self._freezer.move_to(moment)
        async_fire_time_changed(self._hass)
        await self._hass.async_block_till_done()

    def zustand(self, entity_id: str) -> str:
        """Der aktuelle Zustand einer Entität."""
        return self._hass.states.get(entity_id).state

    def attribute(self, entity_id: str) -> dict:
        """Die aktuellen Attribute einer Entität."""
        return self._hass.states.get(entity_id).attributes


@pytest.fixture
async def uhr(hass: HomeAssistant, enable_custom_integrations, smarttimes_payload, freezer):
    """Eingerichteter Eintrag mit einem Günstige-Stunde-Sensor, Start um 08:00.

    08:00 Ortszeit liegt vor dem günstigen Block, der Sensor startet also
    nachweislich im Zustand ``off`` – sonst prüften die Tests unten eine Flanke,
    die es nie gab.
    """
    freezer.move_to(_lokal("08:00"))
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
        subentries_data=[
            {
                "data": {
                    "cheap_hours": 4.0,
                    "cheap_mode": "individual",
                    "exact_hours": True,
                },
                "subentry_type": "cheap_hour",
                "title": "Boiler",
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        yield _Uhr(hass, freezer)


@pytest.fixture
async def uhr_ohne_jitter(ohne_jitter, uhr):
    """Wie ``uhr``, aber mit abgeschalteter Last-Glättung (Phase 0).

    Die Reihenfolge der Parameter ist hier **wesentlich**: ``CheapHourEntity``
    liest die Jitter-Phase einmal beim Anlegen der Entität, also währenddem
    ``uhr`` den Eintrag einrichtet. Stünde ``ohne_jitter`` dahinter, käme der
    Patch zu spät und der Sensor trüge doch seine echte Phase – die Sollzeiten
    unten träfen dann nicht mehr zu. Als eigene Fixture statt als zweiter
    Test-Parameter, damit diese Abhängigkeit festgeschrieben ist und nicht an der
    Parameter-Reihenfolge im einzelnen Test hängt.
    """
    return uhr

async def test_sensor_schaltet_an_der_einschaltflanke_ein(uhr_ohne_jitter):
    """Eine Minute vor dem Block aus, zum Blockbeginn an.

    Ohne Jitter fällt die Einschaltflanke exakt auf den Blockbeginn.
    """
    await uhr_ohne_jitter.vorspulen(BLOCK_BEGINN - timedelta(minutes=1))
    assert uhr_ohne_jitter.zustand(GUENSTIG_SENSOR) == "off"

    await uhr_ohne_jitter.vorspulen(BLOCK_BEGINN)
    assert uhr_ohne_jitter.zustand(GUENSTIG_SENSOR) == "on"


async def test_sensor_schaltet_vorgezogen_wieder_aus(uhr_ohne_jitter):
    """Die Ausschaltflanke liegt um die volle Jitterbreite VOR dem Blockende.

    Das ist die Gleichbehandlung beider Flanken: Es wird nie *nach* dem Ende des
    günstigen Blocks ausgeschaltet, der Verbraucher läuft also zu keinem
    Zeitpunkt in der teureren Preiszone. Bislang war das nur an
    ``jitter.jittered_window`` geprüft, nicht am schaltenden Sensor.
    """
    await uhr_ohne_jitter.vorspulen(AUS_OHNE_JITTER - timedelta(minutes=1))
    assert uhr_ohne_jitter.zustand(GUENSTIG_SENSOR) == "on"

    await uhr_ohne_jitter.vorspulen(AUS_OHNE_JITTER)
    assert uhr_ohne_jitter.zustand(GUENSTIG_SENSOR) == "off"

    # ... und bleibt aus, auch bis zum eigentlichen Blockende.
    await uhr_ohne_jitter.vorspulen(BLOCK_ENDE)
    assert uhr_ohne_jitter.zustand(GUENSTIG_SENSOR) == "off"


async def test_schaltdauer_entspricht_block_minus_jitterbreite(uhr):
    """Mit echter Phase liegt das Fenster im Block und ist L - Jitterbreite lang.

    Ohne den ``ohne_jitter``-Eingriff, also mit der tatsächlichen, aus der
    Untereintrags-ID abgeleiteten Phase. Gemessen werden die Flanken am Sensor,
    indem die Uhr minütlich durch den ganzen Block gedreht wird.
    """
    an_zeiten = []
    moment = BLOCK_BEGINN - timedelta(minutes=5)
    while moment <= BLOCK_ENDE + timedelta(minutes=5):
        await uhr.vorspulen(moment)
        if uhr.zustand(GUENSTIG_SENSOR) == "on":
            an_zeiten.append(moment)
        moment += timedelta(minutes=1)

    assert an_zeiten, "Der Sensor hat im ganzen Block nie eingeschaltet."
    # Das Fenster verlässt den günstigen Block nie – weder vorn noch hinten.
    assert an_zeiten[0] >= BLOCK_BEGINN
    assert an_zeiten[-1] < BLOCK_ENDE
    # Und es ist lückenlos: so viele Minuten wie zwischen erster und letzter.
    assert len(an_zeiten) == int(
        (an_zeiten[-1] - an_zeiten[0]).total_seconds() // 60
    ) + 1
    # Die Einschaltflanke liegt höchstens eine Jitterbreite nach dem Blockbeginn.
    assert an_zeiten[0] <= BLOCK_BEGINN + timedelta(seconds=JITTER_SPAN_SECONDS)
    # Der ausgewiesene Versatz passt zur beobachteten Flanke (minutengenau, weil
    # nur im Minutentakt abgetastet wurde).
    versatz = uhr.attribute(GUENSTIG_SENSOR)["jitter_offset_seconds"]
    assert abs((an_zeiten[0] - BLOCK_BEGINN).total_seconds() - versatz) < 60


async def test_preissensor_folgt_dem_intervallwechsel(uhr):
    """Der Arbeitspreis-Sensor zieht beim Viertelstundenwechsel nach.

    Das prüft die minütliche Neuberechnung selbst: Bliebe sie aus, zeigte der
    Sensor dauerhaft das Intervall, das bei der Einrichtung galt.
    """
    await uhr.vorspulen(_lokal("12:00"))
    assert uhr.attribute(ARBEITSPREIS_SENSOR)["current_start"] == (
        "2026-06-05T12:00:00+02:00"
    )

    await uhr.vorspulen(_lokal("12:20"))
    assert uhr.attribute(ARBEITSPREIS_SENSOR)["current_start"] == (
        "2026-06-05T12:15:00+02:00"
    )


async def test_preissensor_wechselt_an_der_preisstufe(uhr):
    """Beim Stufenwechsel um 16:00 ändert sich der ausgewiesene Arbeitspreis.

    Sollwerte laut Fixture: Stunde 15 liegt in der Stufe 11,316 ct, Stunde 16 in
    der Stufe 13,020 ct – in EUR/kWh also 0,11316 -> 0,1302.
    """
    await uhr.vorspulen(_lokal("15:45"))
    assert float(uhr.zustand(ARBEITSPREIS_SENSOR)) == pytest.approx(0.11316)

    await uhr.vorspulen(_lokal("16:00"))
    assert float(uhr.zustand(ARBEITSPREIS_SENSOR)) == pytest.approx(0.1302)


async def test_naechster_start_springt_nach_dem_block_auf_morgen(uhr_ohne_jitter):
    """Nach dem Ende des heutigen Fensters zeigt der Zeitstempel auf morgen.

    Vor dem Block nennt er den heutigen Beginn, danach den des Folgetags. Beides
    zusammen ist erst über die Zeit hinweg zu sehen – bisher prüften das zwei
    getrennt eingefrorene Momentaufnahmen, die den Übergang selbst ausließen.
    """
    await uhr_ohne_jitter.vorspulen(_lokal("09:00"))
    assert uhr_ohne_jitter.zustand(NAECHSTER_START_SENSOR) == "2026-06-05T08:00:00+00:00"

    await uhr_ohne_jitter.vorspulen(_lokal("14:30"))
    assert uhr_ohne_jitter.zustand(NAECHSTER_START_SENSOR) == "2026-06-06T08:00:00+00:00"
