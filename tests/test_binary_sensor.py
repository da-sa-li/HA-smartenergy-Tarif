"""Tests für die Binary-Sensor-Plattform.

Schwerpunkt ist der Recorder-Ausschluss: Die Attribute ``cheap_intervals`` und
``cheap_windows`` sind minütlich neu berechnete Vorschaulisten. Landen sie in
der Datenbank, wächst diese bei jedem Attributwechsel um die vollständigen
Listen – und ``current_price_ct_kwh`` wechselt mit jedem Preisintervall.
Für ``sensor.py`` wurde das bereits behoben; hier wird es für beide Plattformen
als Invariante festgehalten.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
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
from custom_components.smartenergy.const import (
    FETCH_JITTER_MINUTES,
    JITTER_SPAN_SECONDS,
    NEXT_DAY_PRICES_HOUR,
    SUBENTRY_TYPE_CHEAP_HOUR,
)
from custom_components.smartenergy.sensor import SENSORS, SmartTimesSensor

# Die Fixture deckt den 05.06.2026 ab; 10:00 UTC = 12:00 Ortszeit liegt darin.
# Gleicher Zeitpunkt wie in test_api.py/test_coordinator.py.
ZEITPUNKT = "2026-06-05 10:00:00"


@pytest.fixture
def untereintrag() -> ConfigSubentry:
    """Ein „Günstige Stunde“-Untereintrag, wie ihn der Subentry-Flow anlegt."""
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


# --- Diagnose-Sensor „Preise für morgen verfügbar“ --------------------------- #
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

    # Die API sagt die Preise ab NEXT_DAY_PRICES_HOUR Ortszeit zu; die
    # Integration wartet zusätzlich ihren Abruf-Jitter ab (0 bis unter
    # FETCH_JITTER_MINUTES Minuten, deterministisch je Eintrag und Tag).
    erwartet_ab = datetime.fromisoformat(zustand.attributes["expected_after"])
    assert erwartet_ab.date() == date(2026, 6, 5)
    assert erwartet_ab.hour == NEXT_DAY_PRICES_HOUR
    assert 0 <= erwartet_ab.minute < FETCH_JITTER_MINUTES
    assert (erwartet_ab.second, erwartet_ab.microsecond) == (0, 0)


@pytest.mark.freeze_time("2026-06-05 10:00:00")
async def test_expected_after_ist_genau_die_abruf_schwelle(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Das Attribut nennt exakt den Moment, ab dem die Integration Preise erwartet.

    Gäbe es glatt NEXT_DAY_PRICES_HOUR aus, wäre ein leerer Morgen-Tag zwischen
    17:00 und 17:00 + Jitter fälschlich als überfällig ausgewiesen – obwohl der
    Koordinator bis dahin noch gar keinen Abruf versucht hat. Geprüft wird
    deshalb die Umschaltung selbst und nicht eine fest verdrahtete Uhrzeit: Der
    Jitter hängt an der Eintrags-ID, die je Testlauf neu vergeben wird.
    """
    entry = await _richte_ein(hass, smarttimes_payload)
    coordinator = entry.runtime_data

    erwartet_ab = datetime.fromisoformat(
        hass.states.get(MORGEN_ENTITAET).attributes["expected_after"]
    )

    assert coordinator._next_day_prices_due(erwartet_ab) is True
    assert (
        coordinator._next_day_prices_due(erwartet_ab - timedelta(minutes=1))
        is False
    )


@pytest.mark.freeze_time("2026-06-06 10:00:00")  # 12:00 Ortszeit am letzten Tag
async def test_morgenpreise_fehlen(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Am 06.06. fehlen die Preise für den 07.06. – der Sensor ist aus.

    Genau diesen Fall konnte eine Automatisierung bisher nicht erkennen:
    ``prices_tomorrow`` ist hier und bei „gar keine Preise“ gleichermaßen leer.
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


# --- Attributwerte und Last-Glättung am laufenden Sensor -------------------- #
#
# Die Attribute wurden bisher nur auf ihre *Form* geprüft (Listen-Ausschluss für
# den Recorder). Ihre Werte sind aber der öffentliche Vertrag, auf dem die
# Automatisierungsbeispiele im Wiki stehen.
#
# Sollwerte von Hand, smartTIMES + Netzgebiet Wien, brutto, 05.06.2026 12:00
# Ortszeit; Herleitung wie im Kopf des Zeitstempel-Abschnitts in
# tests/test_sensor.py: Die 16 günstigsten Viertelstunden bei cheap_hours = 4,0
# und exact_hours = ein bilden den Block 10:00-14:00, alle im SNAP-Fenster:
#   (11,316/1,2 gerundet 9,43 + 0,72 Abgaben + 5,58 Netznutzung + 0,700 Verlust)
#   * 1,2 = 19,7160 ct  ->  0,19716 EUR/kWh
SCHWELLWERT_EUR = 0.19716
BLOCK_BEGINN = datetime(2026, 6, 5, 10, 0, tzinfo=dt_util.get_time_zone("Europe/Vienna"))
BLOCK_ENDE = datetime(2026, 6, 5, 14, 0, tzinfo=dt_util.get_time_zone("Europe/Vienna"))

# Feste Untereintrags-IDs statt der sonst je Lauf neu vergebenen ULIDs: Die
# Jitter-Phase leitet sich aus der ID ab, und nur mit festen IDs sind die
# Versätze zweier Sensoren reproduzierbar verschieden. Mit zufälligen IDs wäre
# ein Gleichstand zwar selten, aber möglich – der Test würde gelegentlich grundlos
# fehlschlagen.
ID_BOILER = "01BOILER00000000000000000A"
ID_WALLBOX = "01WALLBOX0000000000000000B"


async def _richte_mit_verbrauchern_ein(
    hass: HomeAssistant, payload: dict, *ids_und_namen: tuple[str, str]
) -> MockConfigEntry:
    """Richtet einen smartTIMES-Eintrag (Wien) mit Günstig-Stunde-Sensoren ein."""
    parsed = SmartTimesApiClient._parse(payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
        subentries_data=[
            {
                "subentry_id": subentry_id,
                "data": {
                    "cheap_hours": 4.0,
                    "cheap_mode": "individual",
                    "exact_hours": True,
                },
                "subentry_type": SUBENTRY_TYPE_CHEAP_HOUR,
                "title": titel,
                "unique_id": None,
            }
            for subentry_id, titel in ids_und_namen
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
    return entry


@pytest.mark.freeze_time(ZEITPUNKT)  # 12:00 Ortszeit, mitten im Block
async def test_guenstig_sensor_attribute_tragen_die_erwarteten_werte(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Schwellwert, aktueller Preis und Einstellungen stehen als Werte fest."""
    await _richte_mit_verbrauchern_ein(
        hass, smarttimes_payload, (ID_BOILER, "Boiler")
    )

    zustand = hass.states.get("binary_sensor.boiler_cheap_hour")
    attribute = zustand.attributes

    assert zustand.state == "on"  # 12:00 liegt im Block 10:00-14:00
    assert attribute["cheap_hours"] == 4.0
    assert attribute["cheap_mode"] == "individual"
    assert attribute["exact_hours"] is True
    assert attribute["unit"] == "EUR/kWh"
    assert attribute["vat_included"] is True
    assert attribute["threshold_eur_kwh"] == pytest.approx(SCHWELLWERT_EUR)
    # Das laufende Intervall gehört selbst zu den günstigsten, aktueller Preis
    # und Schwellwert fallen hier also zusammen.
    assert attribute["current_price_eur_kwh"] == pytest.approx(SCHWELLWERT_EUR)
    # 16 Viertelstunden = 4 Stunden, exakt wie eingestellt.
    assert len(attribute["cheap_intervals"]) == 16
    assert attribute["cheap_intervals"][0]["start"] == "2026-06-05T10:00:00+02:00"
    assert attribute["cheap_intervals"][-1]["end"] == "2026-06-05T14:00:00+02:00"


@pytest.mark.freeze_time(ZEITPUNKT)
async def test_ausgewiesener_versatz_ist_der_tatsaechliche_schaltversatz(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """``jitter_offset_seconds`` nennt genau die Verzögerung des Einschaltens.

    Das Attribut ist die einzige Stelle, an der ein Nutzer den Versatz seines
    Sensors ablesen kann. Liefe es gegen einen anderen Wert als die tatsächliche
    Flanke, wäre es schlimmer als gar kein Attribut – niemand würde den
    Widerspruch bemerken.
    """
    await _richte_mit_verbrauchern_ein(
        hass, smarttimes_payload, (ID_BOILER, "Boiler")
    )

    attribute = hass.states.get("binary_sensor.boiler_cheap_hour").attributes

    (fenster,) = attribute["cheap_windows"]
    ein = datetime.fromisoformat(fenster["on"])
    aus = datetime.fromisoformat(fenster["off"])

    # Beide Flanken wandern nach innen, das Fenster verlässt den Block nie.
    assert BLOCK_BEGINN <= ein <= BLOCK_BEGINN + timedelta(seconds=JITTER_SPAN_SECONDS)
    assert BLOCK_ENDE - timedelta(seconds=JITTER_SPAN_SECONDS) <= aus <= BLOCK_ENDE
    # Die Fensterlänge ist für jeden Sensor dieselbe: Blocklänge minus Jitterbreite.
    assert aus - ein == (BLOCK_ENDE - BLOCK_BEGINN) - timedelta(
        seconds=JITTER_SPAN_SECONDS
    )
    # Und der ausgewiesene Versatz ist genau diese Verzögerung.
    assert attribute["jitter_offset_seconds"] == round(
        (ein - BLOCK_BEGINN).total_seconds()
    )
    # Kein Überschuss-Intervall: exact_hours ist an, es wird nie erweitert.
    assert fenster["exceeds_cheap_hours"] is False


@pytest.mark.freeze_time(ZEITPUNKT)
async def test_zwei_verbraucher_schalten_zu_verschiedenen_zeiten(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Zwei Sensoren desselben Eintrags bekommen verschiedene Versätze.

    Das ist der ganze Zweck der Last-Glättung. Bisher prüfte das nichts: Die
    Tests in ``test_jitter.py`` reichen die Phase von Hand hinein, und die
    Sensor-Tests deckten nur den zugesagten *Bereich* ab – ein fest auf 0
    verdrahteter Versatz wäre darin unauffällig geblieben, obwohl dann alle
    Verbraucher wieder gleichzeitig schalteten.
    """
    await _richte_mit_verbrauchern_ein(
        hass, smarttimes_payload, (ID_BOILER, "Boiler"), (ID_WALLBOX, "Wallbox")
    )

    boiler = hass.states.get("binary_sensor.boiler_cheap_hour").attributes
    wallbox = hass.states.get("binary_sensor.wallbox_cheap_hour").attributes

    assert boiler["jitter_offset_seconds"] != wallbox["jitter_offset_seconds"]
    for attribute in (boiler, wallbox):
        assert 0 <= attribute["jitter_offset_seconds"] <= JITTER_SPAN_SECONDS
    # Verschoben ist die Lage des Fensters, nicht seine Länge – beide laufen
    # gleich lang.
    def laenge(attribute: dict) -> timedelta:
        (fenster,) = attribute["cheap_windows"]
        return datetime.fromisoformat(fenster["off"]) - datetime.fromisoformat(
            fenster["on"]
        )

    assert laenge(boiler) == laenge(wallbox)


@pytest.mark.freeze_time("2026-06-07 10:00:00")  # 12:00 Ortszeit, nach der Fixture
async def test_ohne_preisabdeckung_ist_der_zustand_unbekannt(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Deckt kein Intervall „jetzt“ ab, meldet der Sensor ``unknown``.

    Die Fixture endet am 07.06. um 00:00. ``off`` wäre hier die falsche Antwort:
    Eine Automatisierung liest das als „gerade nicht günstig“ und schaltet den
    Verbraucher ab, obwohl in Wahrheit schlicht keine Preise vorliegen.
    """
    await _richte_mit_verbrauchern_ein(
        hass, smarttimes_payload, (ID_BOILER, "Boiler")
    )

    assert hass.states.get("binary_sensor.boiler_cheap_hour").state == "unknown"
