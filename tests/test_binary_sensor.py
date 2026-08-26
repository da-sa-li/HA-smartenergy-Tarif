"""Tests für die Binary-Sensor-Plattform.

Schwerpunkt ist der Recorder-Ausschluss: Die Attribute ``cheap_intervals`` und
``cheap_windows`` sind minütlich neu berechnete Vorschaulisten. Landen sie in
der Datenbank, wächst diese bei jedem Attributwechsel um die vollständigen
Listen – und ``current_price_ct_kwh`` wechselt mit jedem Preisintervall.
Für ``sensor.py`` wurde das bereits behoben; hier wird es für beide Plattformen
als Invariante festgehalten.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.binary_sensor import CheapHourBinarySensor
from custom_components.smartenergy.const import SUBENTRY_TYPE_CHEAP_HOUR
from custom_components.smartenergy.sensor import SENSORS, SmartTimesSensor

# Die Fixture deckt den 05.06.2026 ab; 10:00 UTC = 12:00 Ortszeit liegt darin.
# Gleicher Zeitpunkt wie in test_api.py/test_coordinator.py.
ZEITPUNKT = "2026-06-05 10:00:00"


@pytest.fixture
def untereintrag() -> ConfigSubentry:
    """Ein „Günstige Stunde"-Untereintrag, wie ihn der Subentry-Flow anlegt."""
    return ConfigSubentry(
        data={"cheap_hours": 4.0, "cheap_mode": "individual", "exact_hours": False},
        subentry_type=SUBENTRY_TYPE_CHEAP_HOUR,
        title="Boiler",
        unique_id=None,
    )


@pytest.fixture
def cheap_hour_sensor(make_data, smarttimes_payload, untereintrag):
    """Ein Binary-Sensor auf echten Fixture-Daten, ohne laufende HA-Instanz."""
    daten = make_data(smarttimes_payload, grid_zone="wien")
    koordinator = SimpleNamespace(data=daten)
    return CheapHourBinarySensor(koordinator, untereintrag)


@pytest.mark.freeze_time(ZEITPUNKT)
def test_listen_attribute_sind_vom_recorder_ausgeschlossen(cheap_hour_sensor):
    """Jedes Listen-Attribut muss in ``_unrecorded_attributes`` stehen.

    Als Invariante formuliert und nicht als Aufzählung: Ein künftig ergänztes
    Listen-Attribut fällt damit automatisch auf, statt still mitgeschrieben zu
    werden.
    """
    attribute = cheap_hour_sensor.extra_state_attributes

    listen = {name for name, wert in attribute.items() if isinstance(wert, list)}
    assert listen, "Erwartet werden Listen-Attribute – sonst prüft der Test nichts."
    assert listen <= set(cheap_hour_sensor._unrecorded_attributes), (
        "Nicht ausgeschlossene Listen-Attribute: "
        f"{sorted(listen - set(cheap_hour_sensor._unrecorded_attributes))}"
    )


@pytest.mark.freeze_time(ZEITPUNKT)
def test_ausgeschlossene_attribute_existieren_auch(cheap_hour_sensor):
    """Kein Eintrag in ``_unrecorded_attributes`` läuft ins Leere.

    Schützt davor, dass ein Attribut umbenannt wird und der Ausschluss dann
    unbemerkt wirkungslos ist.
    """
    attribute = cheap_hour_sensor.extra_state_attributes

    assert set(cheap_hour_sensor._unrecorded_attributes) <= set(attribute)


def test_erwartete_listen_namen(cheap_hour_sensor):
    """Die beiden bekannten Vorschaulisten sind ausgeschlossen (Regression)."""
    assert set(cheap_hour_sensor._unrecorded_attributes) == {
        "cheap_intervals",
        "cheap_windows",
    }


def test_sensor_plattform_schliesst_ihre_listen_ebenfalls_aus():
    """Gegenprobe für ``sensor.py`` – dort wurde der Ausschluss zuerst eingeführt."""
    assert set(SmartTimesSensor._unrecorded_attributes) == {
        "prices_today",
        "prices_tomorrow",
    }
    # Die Beschreibungen mit Attributen sind genau die beiden Preis-Sensoren.
    assert {beschreibung.key for beschreibung in SENSORS} >= {
        "working_price",
        "total_price",
    }


# --- Diagnose-Sensor „Preise für morgen verfügbar" --------------------------- #
#
# Beide Fixtures decken genau den 05. und 06.06.2026 ab (je 96 Viertelstunden,
# letztes Intervall endet am 07.06. um 00:00). Vom 05.06. aus gesehen ist der
# morgige Tag also vollständig vorhanden, vom 06.06. aus gar nicht – das ergibt
# ohne weiteres Zutun beide Zustände.
DOMAIN = "smartenergy"
MORGEN_ENTITAET = (
    "binary_sensor.smarttimes_strompreishelfer_prices_for_tomorrow_available"
)


async def _richte_ein(hass: HomeAssistant, payload: dict) -> MockConfigEntry:
    """Richtet einen smartTIMES-Eintrag ohne Untereintrag ein."""
    parsed = SmartTimesApiClient._parse(payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_morgenpreise_vorhanden(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Am 05.06. liegen die Preise für den 06.06. vollständig vor."""
    await _richte_ein(hass, smarttimes_payload)

    zustand = hass.states.get(MORGEN_ENTITAET)
    assert zustand.state == "on"
    # 96 Viertelstunden = ein vollständiger Tag.
    assert zustand.attributes["price_count"] == 96
    # Die API sagt die Preise ab NEXT_DAY_PRICES_HOUR Ortszeit zu.
    assert zustand.attributes["expected_after"] == "2026-06-05T17:00:00+02:00"


@pytest.mark.freeze_time("2026-06-06 10:00:00")  # 12:00 Ortszeit am letzten Tag
async def test_morgenpreise_fehlen(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Am 06.06. fehlen die Preise für den 07.06. – der Sensor ist aus.

    Genau diesen Fall konnte eine Automatisierung bisher nicht erkennen:
    ``prices_tomorrow`` ist hier und bei „gar keine Preise" gleichermaßen leer.
    """
    await _richte_ein(hass, smarttimes_payload)

    zustand = hass.states.get(MORGEN_ENTITAET)
    assert zustand.state == "off"
    assert zustand.attributes["price_count"] == 0


@pytest.mark.freeze_time("2026-06-05 10:00:00")
async def test_morgenpreise_sensor_ist_diagnose_ohne_geraeteklasse(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Diagnose-Kategorie, aber keine device_class.

    ``PROBLEM`` kehrte die Bedeutung um und wiese den planmäßigen Zustand vor
    der Veröffentlichungszeit als Störung aus.
    """
    entry = await _richte_ein(hass, smarttimes_payload)

    eintrag = er.async_get(hass).async_get(MORGEN_ENTITAET)
    assert eintrag.unique_id == f"{entry.entry_id}_tomorrow_prices"
    assert eintrag.entity_category is EntityCategory.DIAGNOSTIC
    assert "device_class" not in hass.states.get(MORGEN_ENTITAET).attributes


@pytest.mark.parametrize(
    "zeitpunkt", ["2026-06-05 10:00:00", "2026-06-06 10:00:00"]
)
async def test_koordinator_und_datenklasse_sind_sich_einig(
    hass: HomeAssistant,
    enable_custom_integrations,
    smarttimes_payload,
    freezer,
    zeitpunkt,
):
    """Beide Sichten auf die Morgen-Preise liefern dasselbe Ergebnis.

    ``_has_tomorrow_prices`` steuert den Abruf und liest deshalb das rohe
    API-Ergebnis, ``has_prices_for`` die aufbereiteten Daten. Die Doppelung ist
    gewollt (unterschiedliche Lebensdauer), das Ergebnis darf aber nicht
    auseinanderlaufen.
    """
    freezer.move_to(zeitpunkt)
    entry = await _richte_ein(hass, smarttimes_payload)
    coordinator = entry.runtime_data

    jetzt = dt_util.now()
    morgen = jetzt.date() + timedelta(days=1)
    assert coordinator._has_tomorrow_prices(jetzt) == (
        coordinator.data.has_prices_for(morgen)
    )
