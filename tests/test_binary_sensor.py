"""Tests für den „Günstige Stunde"-Binary-Sensor.

Schwerpunkt ist der Recorder-Ausschluss: Die Attribute ``cheap_intervals`` und
``cheap_windows`` sind minütlich neu berechnete Vorschaulisten. Landen sie in
der Datenbank, wächst diese bei jedem Attributwechsel um die vollständigen
Listen – und ``current_price_ct_kwh`` wechselt mit jedem Preisintervall.
Für ``sensor.py`` wurde das bereits behoben; hier wird es für beide Plattformen
als Invariante festgehalten.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigSubentry

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
