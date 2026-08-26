"""Tests für die Sensor-Plattform.

Geprüft wird, welche Entitäten ein Tarif überhaupt hervorbringt. Die
Grundgebühr ist der einzige Sensor, dessen Datengrundlage optional ist:
smartTIMES liefert den ``basicFee``-Block der API, smartCONTROL nicht.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.const import JITTER_SPAN_SECONDS

from tests.conftest import VIENNA

DOMAIN = "smartenergy"


async def _richte_ein(hass: HomeAssistant, payload: dict, tarif: str) -> MockConfigEntry:
    """Richtet einen Eintrag mit der übergebenen API-Antwort ein."""
    parsed = SmartTimesApiClient._parse(payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": tarif, "include_vat": True, "grid_zone": "none"},
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


def _sensor_schluessel(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    """Die Beschreibungs-Schlüssel aller Sensoren des Eintrags.

    Die unique_id lautet ``{entry_id}_{key}`` (siehe SmartTimesSensor).
    """
    registry = er.async_get(hass)
    return {
        eintrag.unique_id.removeprefix(f"{entry.entry_id}_")
        for eintrag in er.async_entries_for_config_entry(registry, entry.entry_id)
        if eintrag.domain == "sensor"
    }


async def test_smarttimes_hat_grundgebuehr_sensor(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """smartTIMES liefert einen basicFee-Block – der Sensor entsteht."""
    entry = await _richte_ein(hass, smarttimes_payload, "smarttimes")

    assert "basic_fee" in _sensor_schluessel(hass, entry)

    # Erster basicFee-Eintrag der Fixture: values[0].value = 2.988 (brutto,
    # wie geliefert; include_vat=True). Vgl. tests/test_api.py und
    # tests/test_coordinator_math.py.
    # Entity-ID nach der englischen Übersetzung, die das Test-Harness verwendet.
    zustand = hass.states.get("sensor.smarttimes_strompreishelfer_basic_fee")
    assert zustand is not None
    assert float(zustand.state) == pytest.approx(2.988)


async def test_smartcontrol_hat_keinen_grundgebuehr_sensor(
    hass: HomeAssistant, enable_custom_integrations, smartcontrol_payload
):
    """smartCONTROL liefert keinen basicFee-Block – der Sensor entfällt.

    Vorher wurde er trotzdem angelegt und stand dauerhaft auf „unbekannt".
    """
    entry = await _richte_ein(hass, smartcontrol_payload, "smartcontrol")

    schluessel = _sensor_schluessel(hass, entry)
    assert "basic_fee" not in schluessel
    # Alle übrigen Sensoren sind unverändert vorhanden.
    assert schluessel == {
        "working_price",
        "total_price",
        "average_today",
        "lowest_today",
        "highest_today",
    }


async def test_warnung_bei_abweichender_grundgebuehr_einheit(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload, caplog
):
    """Meldet die API eine andere Einheit, wird gewarnt.

    Die Anzeige-Einheit ist fest hinterlegt. Wechselte die API auf z. B.
    „EUR/year", zeigte der Sensor sonst stillschweigend eine falsche an.
    """
    payload = dict(smarttimes_payload)
    payload["basicFee"] = dict(payload["basicFee"], unit="EUR/year")

    await _richte_ein(hass, payload, "smarttimes")

    assert "EUR/year" in caplog.text
    assert "EUR/month" in caplog.text


# Sollwerte von Hand aus tests/fixtures/smarttimes.json abgeleitet.
#
# Der 05.06.2026 hat als Zeittarif genau drei Preisstufen zu je 32
# Viertelstunden (Arbeitspreis, brutto ct/kWh):
#     11,316 | 13,020 | 15,852
# Arbeitspreis-Kennzahlen (jede Stufe gleich oft, also einfaches Mittel):
#     Ø   = (11,316 + 13,020 + 15,852) / 3 = 40,188 / 3 = 13,396 ct
#     min = 11,316 ct      max = 15,852 ct
#
# Gesamtpreis ohne Netzgebiet: Nebenkosten netto = Elektrizitätsabgabe 0,10
# + Erneuerbaren-Förderbeitrag 0,62 = 0,72 ct/kWh (surcharges.py, Stand 2026).
# Konvention: netto summieren, USt. einmal am Ende  ->  (brutto/1,2 + 0,72) * 1,2
#     11,316 -> ( 9,43 + 0,72) * 1,2 = 12,180 ct
#     13,020 -> (10,85 + 0,72) * 1,2 = 13,884 ct
#     15,852 -> (13,21 + 0,72) * 1,2 = 16,716 ct
#     Ø   = (12,180 + 13,884 + 16,716) / 3 = 42,780 / 3 = 14,260 ct
#     min = 12,180 ct      max = 16,716 ct
#
# Die Sensoren geben EUR/kWh aus, also jeweils geteilt durch 100. Der
# Coordinator rechnet weiterhin in ct – umgerechnet wird erst in den Entitäten.
ARBEITSPREIS = {"avg": 0.13396, "min": 0.11316, "max": 0.15852}
GESAMTPREIS = {"avg": 0.1426, "min": 0.1218, "max": 0.16716}


@pytest.mark.freeze_time("2026-06-05 10:00:00")
async def test_arbeitspreis_kennzahlen_heissen_eindeutig(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Die Kennzahlen des Arbeitspreis-Sensors tragen "working_price" im Namen.

    Sie meinen den reinen Arbeitspreis, die gleichnamigen Sensoren dagegen den
    Gesamtpreis. Vorher hießen beide gleich, was sich am Wert nicht erkennen
    ließ.
    """
    await _richte_ein(hass, smarttimes_payload, "smarttimes")

    attribute = hass.states.get(
        "sensor.smarttimes_strompreishelfer_energy_price"
    ).attributes

    assert attribute["average_working_price_today"] == pytest.approx(ARBEITSPREIS["avg"])
    assert attribute["lowest_working_price_today"] == pytest.approx(ARBEITSPREIS["min"])
    assert attribute["highest_working_price_today"] == pytest.approx(ARBEITSPREIS["max"])

    # Auch der nächste Preis ist eindeutig benannt und weiterhin vorhanden.
    assert "next_working_price" in attribute
    assert "next_working_price_start" in attribute

    # Die alten, mehrdeutigen Namen sind fort (BREAKING).
    for alt in (
        "average_today",
        "lowest_today",
        "highest_today",
        "next_price",
        "next_price_start",
    ):
        assert alt not in attribute, f"{alt} sollte umbenannt sein"


@pytest.mark.freeze_time("2026-06-05 10:00:00")
async def test_arbeitspreis_und_gesamtpreis_sind_verschiedene_groessen(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Beide Kennzahlsätze existieren nebeneinander und unterscheiden sich.

    Das ist der eigentliche Grund für die Umbenennung: Wer den falschen Satz
    liest, rechnet still mit dem Arbeitspreis statt mit den Gesamtkosten.
    """
    await _richte_ein(hass, smarttimes_payload, "smarttimes")

    arbeitspreis = hass.states.get(
        "sensor.smarttimes_strompreishelfer_energy_price"
    ).attributes
    gesamtpreis = hass.states.get(
        "sensor.smarttimes_strompreishelfer_total_price"
    ).attributes

    # Der Gesamtpreis-Sensor behält seine Namen – sie decken sich mit den
    # gleichnamigen Sensor-Entitäten.
    assert gesamtpreis["average_today"] == pytest.approx(GESAMTPREIS["avg"])
    assert gesamtpreis["lowest_today"] == pytest.approx(GESAMTPREIS["min"])
    assert gesamtpreis["highest_today"] == pytest.approx(GESAMTPREIS["max"])

    # Und sie sind tatsächlich andere Zahlen als die Arbeitspreis-Kennzahlen.
    assert gesamtpreis["average_today"] != pytest.approx(
        arbeitspreis["average_working_price_today"]
    )


def test_alle_preissensoren_melden_eur_pro_kwh():
    """Kein Preissensor fällt auf ct/kWh zurück.

    Als Invariante über SENSORS formuliert: Ein künftig ergänzter Sensor, der
    die Einheit vergisst oder ct setzt, fällt damit auf.
    """
    from custom_components.smartenergy.const import (
        UNIT_EUR_PER_KWH,
        UNIT_EUR_PER_MONTH,
    )
    from custom_components.smartenergy.sensor import SENSORS

    for beschreibung in SENSORS:
        if beschreibung.key == "basic_fee":
            # Begründete Ausnahme: eine monatliche Pauschale, kein Arbeitspreis.
            # Sprachneutral, weil Home Assistant Einheiten nicht übersetzt.
            assert beschreibung.unit == UNIT_EUR_PER_MONTH == "EUR/month"
            continue
        assert beschreibung.unit == UNIT_EUR_PER_KWH, (
            f"{beschreibung.key} meldet {beschreibung.unit!r} statt EUR/kWh"
        )


@pytest.mark.freeze_time("2026-06-05 10:00:00")
async def test_keine_ct_attribute_mehr(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Kein Attribut trägt noch ct im Namen – über beide Plattformen.

    Ausgenommen ist ``source_unit``: Es benennt bewusst die Einheit, in der die
    API liefert und der Coordinator rechnet.
    """
    await _richte_ein(hass, smarttimes_payload, "smarttimes")

    for entity_id in (
        "sensor.smarttimes_strompreishelfer_energy_price",
        "sensor.smarttimes_strompreishelfer_total_price",
    ):
        attribute = hass.states.get(entity_id).attributes
        uebrig = [
            name
            for name in attribute
            if ("_ct" in name or name.endswith("_ct_kwh") or name == "unit_ct")
        ]
        assert not uebrig, f"{entity_id} hat noch ct-Attribute: {uebrig}"

        # Die Einheit wird ausgewiesen, und zwar als EUR/kWh. source_unit gibt
        # den Einheiten-String der API wieder – die smartTIMES-Fixture meldet
        # "cent/kWh", gleichbedeutend mit ct/kWh.
        assert attribute["unit"] == "EUR/kWh"
        assert attribute["source_unit"] == "cent/kWh"


def test_preissensoren_fuehren_langzeitstatistik():
    """Jeder Preissensor trägt eine ``state_class``.

    Ohne sie legt der Recorder keine Langzeitstatistik an und der Sensor fehlt
    in Statistik-Karten. Die Grundgebühr ist ausgenommen: eine Pauschale, die
    sich höchstens jährlich ändert, gewinnt dadurch nichts.
    """
    from homeassistant.components.sensor import SensorStateClass

    from custom_components.smartenergy.sensor import SENSORS

    for beschreibung in SENSORS:
        if beschreibung.key == "basic_fee":
            assert beschreibung.state_class is None
            continue
        assert beschreibung.state_class == SensorStateClass.MEASUREMENT, (
            f"{beschreibung.key} ohne state_class"
        )


# --- Zeitstempel-Sensor „Nächster günstiger Start" --------------------------- #
#
# Sollwerte von Hand aus der smartTIMES-Fixture und den hinterlegten Sätzen
# abgeleitet (Netzgebiet Wien, brutto, cheap_hours = 4,0, exact_hours = ein):
#
# Preisstufen je Tag (brutto ct/kWh Arbeitspreis, an beiden Tagen gleich):
#   11,316 -> Stunden 02,03,10-15
#   13,020 -> Stunden 00,01,04,05,09,16,22,23
#   15,852 -> Stunden 06-08,17-21
#
# Gesamtpreis = (Arbeitspreis netto + Abgaben netto + Netz netto) * 1,2
#   Abgaben netto  = 0,10 (Elektrizitätsabgabe) + 0,62 (Förderbeitrag) = 0,72
#   Wien NE 7 netto = 6,98 Netznutzung + 0,700 Netzverlust
#   SNAP (Apr-Sep, 10-16 Uhr) senkt die Netznutzung um 20 % -> 5,584
#
# Damit für die günstigste Stufe (netto 11,316 / 1,2 = 9,43):
#   Stunden 10-15 (SNAP):   (9,43 + 0,72 + 5,584 + 0,700) * 1,2 = 19,7208
#   Stunden 02-03 (regulär):(9,43 + 0,72 + 6,980 + 0,700) * 1,2 = 21,3960
#
# Günstigste Intervalle sind also die 24 Viertelstunden 10:00-15:45. Bei
# cheap_hours = 4,0 werden ceil(4 * 60 / 15) = 16 gewählt; sortiert nach
# (Wert, Startzeit) sind das die 16 frühesten -> ein zusammenhängender Block
# 10:00-14:00 Ortszeit, an beiden Fixture-Tagen.
BLOCKBEGINN_5 = datetime(2026, 6, 5, 10, 0, tzinfo=VIENNA)
BLOCKBEGINN_6 = datetime(2026, 6, 6, 10, 0, tzinfo=VIENNA)


async def _richte_mit_untereintrag_ein(
    hass: HomeAssistant, payload: dict
) -> tuple[MockConfigEntry, str]:
    """Richtet einen smartTIMES-Eintrag mit einem Günstig-Stunde-Untereintrag ein."""
    parsed = SmartTimesApiClient._parse(payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
        subentries_data=[
            ConfigSubentryData(
                data={
                    "cheap_hours": 4.0,
                    "cheap_mode": "individual",
                    "exact_hours": True,
                },
                subentry_type="cheap_hour",
                title="Boiler",
                unique_id=None,
            )
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
    return entry, next(iter(entry.subentries))


@pytest.fixture
def ohne_jitter():
    """Setzt die Last-Glättung auf 0, damit Sollzeiten exakt prüfbar sind.

    Die Jitter-Phase leitet sich aus der Subentry-ID ab, die je Testlauf neu
    vergeben wird – ohne diesen Eingriff wäre nur ein Intervall prüfbar.
    Gepatcht wird die Bindung in ``entity``, nicht die in ``jitter``: Sonst
    verstellte der Test zugleich den Abruf-Jitter des Koordinators.
    """
    with patch(
        "custom_components.smartenergy.entity.cheap_phase", return_value=0.0
    ):
        yield


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_zeitstempel_sensor_je_untereintrag(
    hass_wien: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Jeder Untereintrag bringt einen Zeitstempel-Sensor mit.

    ``device_class: timestamp`` ist der Zweck der Entität: Nur damit nimmt der
    ``time``-Trigger sie unter ``at:`` an. Einheit und ``state_class`` müssen
    fehlen – Home Assistant weist beides für Zeitstempel zurück.
    """
    entry, subentry_id = await _richte_mit_untereintrag_ein(
        hass_wien, smarttimes_payload
    )

    registry = er.async_get(hass_wien)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{subentry_id}_next_cheap_start"
    )
    assert entity_id is not None
    # Entity-ID nach der englischen Übersetzung, die das Test-Harness verwendet;
    # unter der deutschen lautet sie sensor.boiler_nachster_gunstiger_start.
    assert entity_id == "sensor.boiler_next_cheap_start"

    # Der Sensor hängt am Gerät des Untereintrags, nicht am Hub.
    eintrag = registry.async_get(entity_id)
    assert eintrag.config_subentry_id == subentry_id

    zustand = hass_wien.states.get(entity_id)
    assert zustand.attributes["device_class"] == SensorDeviceClass.TIMESTAMP
    assert "state_class" not in zustand.attributes
    assert "unit_of_measurement" not in zustand.attributes


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit, im Block
async def test_naechster_start_ist_der_folgetags_block(
    hass_wien: HomeAssistant, enable_custom_integrations, smarttimes_payload, ohne_jitter
):
    """Mitten im heutigen Block zeigt der Sensor auf den Block von morgen.

    Um 12:00 Ortszeit läuft der Block 10:00-14:00 bereits; der nächste
    Einschaltzeitpunkt ist damit der 06.06. um 10:00 Ortszeit. Der Zustand wird
    in UTC und auf Sekunden gekürzt ausgegeben.
    """
    await _richte_mit_untereintrag_ein(hass_wien, smarttimes_payload)

    zustand = hass_wien.states.get("sensor.boiler_next_cheap_start")
    assert zustand.state == "2026-06-06T08:00:00+00:00"


@pytest.mark.freeze_time("2026-06-05 06:00:00")  # 08:00 Ortszeit, vor dem Block
async def test_naechster_start_ist_der_heutige_block(
    hass_wien: HomeAssistant, enable_custom_integrations, smarttimes_payload, ohne_jitter
):
    """Vor dem Block zeigt der Sensor auf den heutigen Beginn."""
    await _richte_mit_untereintrag_ein(hass_wien, smarttimes_payload)

    zustand = hass_wien.states.get("sensor.boiler_next_cheap_start")
    assert zustand.state == "2026-06-05T08:00:00+00:00"


@pytest.mark.freeze_time("2026-06-06 14:00:00")  # 16:00 Ortszeit am letzten Tag
async def test_ohne_folgetag_ist_der_sensor_unbekannt(
    hass_wien: HomeAssistant, enable_custom_integrations, smarttimes_payload, ohne_jitter
):
    """Ohne bekanntes nächstes Fenster meldet der Sensor ``unknown``.

    Die Fixture endet mit dem 06.06.; der heutige Block ist um 16:00 vorbei und
    für den 07.06. liegen keine Preise vor. In der Praxis ist das der Zustand
    spät abends, bevor die Preise für den Folgetag veröffentlicht sind – ein
    ``time``-Trigger feuert dann schlicht nicht.
    """
    await _richte_mit_untereintrag_ein(hass_wien, smarttimes_payload)

    zustand = hass_wien.states.get("sensor.boiler_next_cheap_start")
    assert zustand.state == "unknown"


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_naechster_start_liegt_im_jitter_fenster(
    hass_wien: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Ohne Eingriff liegt der Wert im zugesagten Versatz-Bereich.

    Der Jitter verzögert die Einschaltflanke um 0 bis JITTER_SPAN_SECONDS und
    verschiebt sie nie davor (siehe jitter.py). Diese Zusage gilt für jede
    Phase, der Test braucht die konkrete Subentry-ID also nicht zu kennen.
    """
    await _richte_mit_untereintrag_ein(hass_wien, smarttimes_payload)

    zustand = hass_wien.states.get("sensor.boiler_next_cheap_start")
    wert = datetime.fromisoformat(zustand.state)
    assert BLOCKBEGINN_6 <= wert <= BLOCKBEGINN_6 + timedelta(
        seconds=JITTER_SPAN_SECONDS
    )


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_sensor_und_binary_sensor_nennen_denselben_start(
    hass_wien: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Sensorwert und Attribut des Binary-Sensors stimmen überein.

    Zwei unabhängige Codepfade auf dieselbe Zusage – der Sensor enthält den
    Jitter also bereits. Der Zustand ist auf Sekunden gekürzt, das Attribut
    trägt die volle Auflösung; verglichen wird deshalb sekundengenau.
    """
    await _richte_mit_untereintrag_ein(hass_wien, smarttimes_payload)

    sensor = hass_wien.states.get("sensor.boiler_next_cheap_start")
    binary = hass_wien.states.get("binary_sensor.boiler_cheap_hour")
    attribut = datetime.fromisoformat(binary.attributes["next_cheap_start"])

    assert datetime.fromisoformat(sensor.state) == attribut.replace(microsecond=0)
