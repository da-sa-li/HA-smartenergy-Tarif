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
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.const import (
    JITTER_SPAN_SECONDS,
    UNIT_EUR_PER_MONTH,
)
from tests.conftest import VIENNA

DOMAIN = "smartenergy"

# Sensoren, die bewusst keine EUR/kWh melden – mit ihrer jeweils erwarteten
# Einheit. Als Zuordnung statt als Sonderfall im Testkörper: Ein künftiger
# Sensor, der die Einheit schlicht vergisst, steht hier nicht und fällt damit
# weiterhin auf.
KEINE_EUR_PRO_KWH = {
    "basic_fee": UNIT_EUR_PER_MONTH,        # monatliche Pauschale
    "price_rank_today": None,               # Ordnungszahl, dimensionslos
    "price_quantile_today": PERCENTAGE,     # normiert auf 0-100 %
}


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

    Vorher wurde er trotzdem angelegt und stand dauerhaft auf „unbekannt“.
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
        "price_rank_today",
        "price_quantile_today",
    }


async def test_warnung_bei_abweichender_grundgebuehr_einheit(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload, caplog
):
    """Meldet die API eine andere Einheit, wird gewarnt.

    Die Anzeige-Einheit ist fest hinterlegt. Wechselte die API auf z. B.
    „EUR/year“, zeigte der Sensor sonst stillschweigend eine falsche an.
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
    die Einheit vergisst oder ct setzt, fällt damit auf. Die begründeten
    Ausnahmen stehen als Zuordnung in KEINE_EUR_PRO_KWH – jede mit der Einheit,
    die sie stattdessen führen muss. Sprachneutral, weil Home Assistant
    Einheiten nicht übersetzt.
    """
    from custom_components.smartenergy.const import UNIT_EUR_PER_KWH
    from custom_components.smartenergy.sensor import SENSORS

    for beschreibung in SENSORS:
        if beschreibung.key in KEINE_EUR_PRO_KWH:
            assert beschreibung.unit == KEINE_EUR_PRO_KWH[beschreibung.key], (
                f"{beschreibung.key} meldet {beschreibung.unit!r}"
            )
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

    # Die Namensprüfung gilt für jeden Sensor, der überhaupt Attribute führt –
    # auch für die beiden Kennzahl-Sensoren, deren Attribute (quantile_percent,
    # interval_count) bewusst kein ct im Namen tragen.
    for entity_id in (
        "sensor.smarttimes_strompreishelfer_energy_price",
        "sensor.smarttimes_strompreishelfer_total_price",
        "sensor.smarttimes_strompreishelfer_price_rank_today",
        "sensor.smarttimes_strompreishelfer_price_quantile_today",
    ):
        attribute = hass.states.get(entity_id).attributes
        uebrig = [
            name
            for name in attribute
            if ("_ct" in name or name.endswith("_ct_kwh") or name == "unit_ct")
        ]
        assert not uebrig, f"{entity_id} hat noch ct-Attribute: {uebrig}"

    # Die Einheit wird ausgewiesen, und zwar als EUR/kWh. source_unit gibt den
    # Einheiten-String der API wieder – die smartTIMES-Fixture meldet
    # "cent/kWh", gleichbedeutend mit ct/kWh. Beides führen nur die beiden
    # Preissensoren; Rang und Quantil sind keine Preise.
    for entity_id in (
        "sensor.smarttimes_strompreishelfer_energy_price",
        "sensor.smarttimes_strompreishelfer_total_price",
    ):
        attribute = hass.states.get(entity_id).attributes
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


# --- Zeitstempel-Sensor „Nächster günstiger Start“ --------------------------- #
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
#   SNAP (Apr-Sep, 10-16 Uhr) senkt die Netznutzung um 20 % -> 5,58 (die
#   Netzbetreiber weisen den Satz auf zwei Nachkommastellen aus, grid_fees.py
#   führt ihn genauso)
#
# Damit für die günstigste Stufe (netto 11,316 / 1,2 = 9,43):
#   Stunden 10-15 (SNAP):   (9,43 + 0,72 + 5,58 + 0,700) * 1,2 = 19,7160
#   Stunden 02-03 (regulär):(9,43 + 0,72 + 6,98 + 0,700) * 1,2 = 21,3960
#
# Günstigste Intervalle sind also die 24 Viertelstunden 10:00-15:45. Bei
# cheap_hours = 4,0 werden ceil(4 * 60 / 15) = 16 gewählt; sortiert nach
# (Wert, Startzeit) sind das die 16 frühesten -> ein zusammenhängender Block
# 10:00-14:00 Ortszeit, an beiden Fixture-Tagen.
BLOCKBEGINN_5 = datetime(2026, 6, 5, 10, 0, tzinfo=VIENNA)
BLOCKBEGINN_6 = datetime(2026, 6, 6, 10, 0, tzinfo=VIENNA)


async def _richte_ein_wien(hass: HomeAssistant, payload: dict) -> MockConfigEntry:
    """Richtet einen smartTIMES-Eintrag ohne Untereintrag ein (Netzgebiet Wien)."""
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


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_zeitstempel_sensor_je_untereintrag(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Jeder Untereintrag bringt einen Zeitstempel-Sensor mit.

    ``device_class: timestamp`` ist der Zweck der Entität: Nur damit nimmt der
    ``time``-Trigger sie unter ``at:`` an. Einheit und ``state_class`` müssen
    fehlen – Home Assistant weist beides für Zeitstempel zurück.
    """
    _entry, subentry_id = await _richte_mit_untereintrag_ein(
        hass, smarttimes_payload
    )

    registry = er.async_get(hass)
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

    zustand = hass.states.get(entity_id)
    assert zustand.attributes["device_class"] == SensorDeviceClass.TIMESTAMP
    assert "state_class" not in zustand.attributes
    assert "unit_of_measurement" not in zustand.attributes


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit, im Block
async def test_naechster_start_ist_der_folgetags_block(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload, ohne_jitter
):
    """Mitten im heutigen Block zeigt der Sensor auf den Block von morgen.

    Um 12:00 Ortszeit läuft der Block 10:00-14:00 bereits; der nächste
    Einschaltzeitpunkt ist damit der 06.06. um 10:00 Ortszeit. Der Zustand wird
    in UTC und auf Sekunden gekürzt ausgegeben.
    """
    await _richte_mit_untereintrag_ein(hass, smarttimes_payload)

    zustand = hass.states.get("sensor.boiler_next_cheap_start")
    assert zustand.state == "2026-06-06T08:00:00+00:00"


@pytest.mark.freeze_time("2026-06-05 06:00:00")  # 08:00 Ortszeit, vor dem Block
async def test_naechster_start_ist_der_heutige_block(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload, ohne_jitter
):
    """Vor dem Block zeigt der Sensor auf den heutigen Beginn."""
    await _richte_mit_untereintrag_ein(hass, smarttimes_payload)

    zustand = hass.states.get("sensor.boiler_next_cheap_start")
    assert zustand.state == "2026-06-05T08:00:00+00:00"


@pytest.mark.freeze_time("2026-06-06 14:00:00")  # 16:00 Ortszeit am letzten Tag
async def test_ohne_folgetag_ist_der_sensor_unbekannt(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload, ohne_jitter
):
    """Ohne bekanntes nächstes Fenster meldet der Sensor ``unknown``.

    Die Fixture endet mit dem 06.06.; der heutige Block ist um 16:00 vorbei und
    für den 07.06. liegen keine Preise vor. In der Praxis ist das der Zustand
    spät abends, bevor die Preise für den Folgetag veröffentlicht sind – ein
    ``time``-Trigger feuert dann schlicht nicht.
    """
    await _richte_mit_untereintrag_ein(hass, smarttimes_payload)

    zustand = hass.states.get("sensor.boiler_next_cheap_start")
    assert zustand.state == "unknown"


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_naechster_start_liegt_im_jitter_fenster(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Ohne Eingriff liegt der Wert im zugesagten Versatz-Bereich.

    Der Jitter verzögert die Einschaltflanke um 0 bis JITTER_SPAN_SECONDS und
    verschiebt sie nie davor (siehe jitter.py). Diese Zusage gilt für jede
    Phase, der Test braucht die konkrete Subentry-ID also nicht zu kennen.
    """
    await _richte_mit_untereintrag_ein(hass, smarttimes_payload)

    zustand = hass.states.get("sensor.boiler_next_cheap_start")
    wert = datetime.fromisoformat(zustand.state)
    assert BLOCKBEGINN_6 <= wert <= BLOCKBEGINN_6 + timedelta(
        seconds=JITTER_SPAN_SECONDS
    )


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_sensor_und_binary_sensor_nennen_denselben_start(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Sensorwert und Attribut des Binary-Sensors stimmen überein.

    Zwei unabhängige Codepfade auf dieselbe Zusage – der Sensor enthält den
    Jitter also bereits. Der Zustand ist auf Sekunden gekürzt, das Attribut
    trägt die volle Auflösung; verglichen wird deshalb sekundengenau.
    """
    await _richte_mit_untereintrag_ein(hass, smarttimes_payload)

    sensor = hass.states.get("sensor.boiler_next_cheap_start")
    binary = hass.states.get("binary_sensor.boiler_cheap_hour")
    attribut = datetime.fromisoformat(binary.attributes["next_cheap_start"])

    assert datetime.fromisoformat(sensor.state) == attribut.replace(microsecond=0)


@pytest.mark.parametrize(
    ("zeitpunkt", "erwartet"),
    [
        # Die Fixture deckt den 05. und 06.06.2026 ab: Vom 05.06. aus ist der
        # morgige Tag vollständig da, vom 06.06. aus gar nicht.
        ("2026-06-05 10:00:00", True),
        ("2026-06-06 10:00:00", False),
    ],
)
@pytest.mark.parametrize(
    "entitaet",
    [
        "sensor.smarttimes_strompreishelfer_total_price",
        "sensor.smarttimes_strompreishelfer_energy_price",
    ],
)
async def test_prices_tomorrow_valid_an_beiden_preissensoren(
    hass: HomeAssistant,
    enable_custom_integrations,
    smarttimes_payload,
    freezer,
    zeitpunkt,
    erwartet,
    entitaet,
):
    """Beide Preissensoren weisen aus, ob die Morgen-Preise vorliegen.

    Das Attribut steht direkt neben ``prices_tomorrow`` und löst dessen
    Mehrdeutigkeit auf: Eine leere Liste heißt sonst gleichermaßen "noch nicht
    veröffentlicht" und "keine Preise".
    """
    freezer.move_to(zeitpunkt)
    await _richte_ein_wien(hass, smarttimes_payload)

    attribute = hass.states.get(entitaet).attributes
    assert attribute["prices_tomorrow_valid"] is erwartet
    # Gegenprobe: Der Wert deckt sich mit der Liste, die er beschreibt.
    assert attribute["prices_tomorrow_valid"] is bool(attribute["prices_tomorrow"])


# --- Abwicklungsgebühr: von der Tarifwahl bis zum Sensor --------------------- #
#
# Die 1,2 ct/kWh netto wurden bisher ausschließlich dort geprüft, wo der Test sie
# selbst hineinreichte (`make_data(..., handling_fee_net=1.2)`). Ob die
# Tarifwahl im Config-Eintrag sie überhaupt an den Koordinator weiterreicht, war
# von keinem Test gedeckt – ausgerechnet beim geldrelevantesten Schalter des
# Tarifs.
#
# Sollwerte von Hand, smartCONTROL ohne Netzgebiet, brutto, 05.06.2026 12:00
# Ortszeit (Arbeitspreis laut tests/fixtures/smartcontrol.json: 6,446 ct brutto):
#   netto AP        = round(6,446 / 1,2, 4)            = 5,3717
#   Nebenkosten netto = 0,10 + 0,62 + 1,20             = 1,92
#   Summe netto     = 5,3717 + 1,92                    = 7,2917
#   brutto          = round(7,2917 * 1,2, 4)           = 8,7500 ct  -> 0,0875 EUR
# Einzelpositionen brutto (USt. je Position, Summe bleibt dieselbe):
#   Elektrizitätsabgabe 0,10 * 1,2 = 0,12   ct -> 0,0012  EUR
#   Förderbeitrag       0,62 * 1,2 = 0,744  ct -> 0,00744 EUR
#   Abwicklungsgebühr   1,20 * 1,2 = 1,44   ct -> 0,0144  EUR
#   Summe                              2,304 ct -> 0,02304 EUR
SMARTCONTROL_GESAMT_EUR = 0.0875
SMARTCONTROL_GEBUEHR_EUR = 0.0144


@pytest.mark.parametrize(
    ("tarif", "payload_name", "erwartet"),
    [
        # 1,2 ct/kWh netto laut Spezifikation (CLAUDE.md, README) – bewusst als
        # Zahl und nicht als SMARTCONTROL_HANDLING_FEE_NET: Gegen die Konstante
        # zu prüfen hieße, den Wert gegen sich selbst zu prüfen, und ein
        # verstellter Satz änderte Laufzeitwert und Sollwert gemeinsam.
        ("smartcontrol", "smartcontrol_payload", 1.2),
        ("smarttimes", "smarttimes_payload", 0.0),
    ],
)
async def test_abwicklungsgebuehr_haengt_am_gewaehlten_tarif(
    hass: HomeAssistant,
    enable_custom_integrations,
    request: pytest.FixtureRequest,
    tarif: str,
    payload_name: str,
    erwartet: float,
):
    """Nur smartCONTROL bekommt die Abwicklungsgebühr, smartTIMES nicht.

    Prüft die Verdrahtung in ``__init__.async_setup_entry`` selbst: Ohne diesen
    Test bliebe unbemerkt, wenn die Fallunterscheidung wegfiele oder sich
    umdrehte – die Preis-Mathematik dahinter rechnete weiterhin fehlerfrei, nur
    eben mit dem falschen Satz.
    """
    entry = await _richte_ein(hass, request.getfixturevalue(payload_name), tarif)

    assert entry.runtime_data.data.handling_fee_net == pytest.approx(erwartet)


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_abwicklungsgebuehr_erreicht_den_gesamtpreis_sensor(
    hass: HomeAssistant, enable_custom_integrations, smartcontrol_payload
):
    """Der Gesamtpreis-Sensor weist die Gebühr aus und rechnet sie mit ein.

    Sollwerte siehe Herleitung oben. Geprüft wird beides: die eigene Position in
    der Aufschlüsselung *und* ihr Beitrag zum Sensorwert – eine Gebühr, die nur
    im Attribut steht, wäre für die Kostenrechnung wertlos.
    """
    await _richte_ein(hass, smartcontrol_payload, "smartcontrol")

    zustand = hass.states.get("sensor.smartcontrol_strompreishelfer_total_price")
    assert float(zustand.state) == pytest.approx(SMARTCONTROL_GESAMT_EUR)

    aufschluesselung = zustand.attributes["surcharges_eur_kwh"]
    assert aufschluesselung["handling_fee"] == pytest.approx(SMARTCONTROL_GEBUEHR_EUR)
    assert aufschluesselung == pytest.approx(
        {
            "electricity_tax": 0.0012,
            "renewable_support": 0.00744,
            "handling_fee": SMARTCONTROL_GEBUEHR_EUR,
        }
    )


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_smarttimes_weist_keine_abwicklungsgebuehr_aus(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Gegenprobe: Bei smartTIMES fehlt die Position in der Aufschlüsselung."""
    await _richte_ein(hass, smarttimes_payload, "smarttimes")

    aufschluesselung = hass.states.get(
        "sensor.smarttimes_strompreishelfer_total_price"
    ).attributes["surcharges_eur_kwh"]

    assert "handling_fee" not in aufschluesselung
    # Ohne Netzgebiet bleiben genau die beiden bundeseinheitlichen Abgaben.
    assert set(aufschluesselung) == {"electricity_tax", "renewable_support"}


# --- Attributwerte der Preissensoren ---------------------------------------- #
#
# Bisher wurden die Attribute zwar durchlaufen (Namensprüfung, Recorder-
# Ausschluss), ihre *Werte* aber nirgends geprüft. Genau deshalb lag die
# Zeilenabdeckung hoch, während der Inhalt ungesichert war.
#
# Sollwerte von Hand, smartTIMES + Netzgebiet Wien, brutto, 05.06.2026 12:00
# Ortszeit (Herleitung der Preisstufen und Netzsätze siehe Kopf dieses
# Abschnitts weiter oben). 12:00 liegt im SNAP-Fenster, Arbeitspreis 11,316:
#   Nebenkosten netto = 0,72 Abgaben + 5,58 Netznutzung + 0,700 Netzverlust = 7,00
#   Summe brutto      = round(7,00 * 1,2, 4)                    = 8,4000 ct
#   Gesamtpreis       = (11,316/1,2 gerundet 9,43 + 7,00) * 1,2 = 19,7160 ct
#
# Einzelpositionen brutto:
#   Elektrizitätsabgabe 0,10  * 1,2 = 0,12  ct -> 0,0012  EUR
#   Förderbeitrag       0,62  * 1,2 = 0,744 ct -> 0,00744 EUR
#   Netznutzung (SNAP)  5,58  * 1,2 = 6,696 ct -> 0,06696 EUR
#   Netzverlust         0,700 * 1,2 = 0,84  ct -> 0,0084  EUR
#
# Tageskennzahlen Gesamtpreis am 05.06. mit Wien (96 Viertelstunden):
#   19,716 ct x 24 (11,316 in den SNAP-Stunden 10-15)
#   21,396 ct x  8 (11,316 in den Stunden 02-03, regulär)
#   23,100 ct x 32 (13,020: (10,85 + 0,72 + 7,68) * 1,2)
#   25,932 ct x 32 (15,852: (13,21 + 0,72 + 7,68) * 1,2)
#   Summe = 473,184 + 171,168 + 739,200 + 829,824 = 2213,376
#   Ø = 2213,376 / 96 = 23,056 ct    min = 19,716 ct    max = 25,932 ct
GESAMTPREIS_WIEN = {
    "aktuell": 0.19716,
    "nebenkosten_summe": 0.084,
    "arbeitspreis": 0.11316,
    "avg": 0.23056,
    "min": 0.19716,
    "max": 0.25932,
}


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit, im SNAP-Fenster
async def test_gesamtpreis_attribute_tragen_die_erwarteten_werte(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Die Aufschlüsselung des Gesamtpreis-Sensors stimmt Position für Position.

    Die Summe allein genügt nicht: Ein Vorzeichen- oder Zuordnungsfehler
    zwischen Netznutzung und Netzverlust bliebe darin unsichtbar.
    """
    await _richte_ein_wien(hass, smarttimes_payload)

    zustand = hass.states.get("sensor.smarttimes_strompreishelfer_total_price")
    attribute = zustand.attributes

    assert float(zustand.state) == pytest.approx(GESAMTPREIS_WIEN["aktuell"])
    assert attribute["vat_included"] is True
    assert attribute["vat_rate"] == pytest.approx(0.20)
    assert attribute["grid_zone"] == "Wien"
    assert attribute["snap_active"] is True
    assert attribute["working_price_eur_kwh"] == pytest.approx(
        GESAMTPREIS_WIEN["arbeitspreis"]
    )
    assert attribute["surcharges_eur_kwh"] == pytest.approx(
        {
            "electricity_tax": 0.0012,
            "renewable_support": 0.00744,
            "grid_usage": 0.06696,
            "grid_loss": 0.0084,
        }
    )
    assert attribute["surcharges_total_eur_kwh"] == pytest.approx(
        GESAMTPREIS_WIEN["nebenkosten_summe"]
    )
    assert attribute["total_eur_kwh"] == pytest.approx(GESAMTPREIS_WIEN["aktuell"])
    assert attribute["average_today"] == pytest.approx(GESAMTPREIS_WIEN["avg"])
    assert attribute["lowest_today"] == pytest.approx(GESAMTPREIS_WIEN["min"])
    assert attribute["highest_today"] == pytest.approx(GESAMTPREIS_WIEN["max"])


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_gesamtpreis_attribut_deckt_sich_mit_dem_sensorwert(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """``total_eur_kwh`` und der Zustand entstehen aus zwei verschiedenen Rechnungen.

    Der Zustand summiert netto und wendet die USt. einmal am Ende an
    (``all_in_value``); das Attribut addiert den bereits brutto gelieferten
    Arbeitspreis zur brutto ausgewiesenen Nebenkostensumme. In exakter Arithmetik
    ist das dasselbe – zwei getrennt gerundete Wege können aber auseinander
    laufen, und ein Nutzer, der beides nebeneinander sieht, hielte das für einen
    Fehler.
    """
    await _richte_ein_wien(hass, smarttimes_payload)

    zustand = hass.states.get("sensor.smarttimes_strompreishelfer_total_price")
    assert float(zustand.state) == zustand.attributes["total_eur_kwh"]


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit
async def test_arbeitspreis_attribute_tragen_die_erwarteten_werte(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Der Arbeitspreis-Sensor weist Intervall, Folgepreis und Grundgebühr aus.

    Ergänzt ``test_arbeitspreis_kennzahlen_heissen_eindeutig``, das bisher nur
    die *Namen* der Kennzahlen prüfte.
    """
    await _richte_ein_wien(hass, smarttimes_payload)

    attribute = hass.states.get(
        "sensor.smarttimes_strompreishelfer_energy_price"
    ).attributes

    assert attribute["tariff"] == "smartTIMES"
    assert attribute["interval_minutes"] == 15
    assert attribute["vat_included"] is True
    # Laufendes Viertelstundenintervall 12:00-12:15 (Fixture-Raster).
    assert attribute["current_start"] == "2026-06-05T12:00:00+02:00"
    assert attribute["current_end"] == "2026-06-05T12:15:00+02:00"
    # Das direkt folgende Intervall liegt in derselben Preisstufe (11,316).
    assert attribute["next_working_price_start"] == "2026-06-05T12:15:00+02:00"
    assert attribute["next_working_price"] == pytest.approx(0.11316)
    # Grundgebühr wie geliefert (brutto), samt Einheit der API.
    assert attribute["basic_fee"] == pytest.approx(2.988)
    assert attribute["basic_fee_unit"] == "EUR/month"
    # Der Arbeitspreis kennt keine Netzentgelte – die Kennzahlen bleiben also
    # dieselben wie ohne Netzgebiet.
    assert attribute["average_working_price_today"] == pytest.approx(
        ARBEITSPREIS["avg"]
    )


# --- Preisrang und Preisquantil --------------------------------------------- #
#
# Sollwerte von Hand, smartTIMES + Netzgebiet Wien, brutto, 05.06.2026 12:00
# Ortszeit. Die Tagesverteilung ist dieselbe wie oben bei GESAMTPREIS_WIEN
# hergeleitet – vier Gesamtpreis-Stufen, weil das SNAP-Fenster die günstigste
# Arbeitspreis-Stufe (11,316) in zwei verschieden teure Hälften spaltet:
#   19,716 ct x 24 (SNAP-Stunden 10-15)  -> cheaper= 0, equal=24
#   21,396 ct x  8 (Stunden 02-03)       -> cheaper=24, equal= 8
#   23,100 ct x 32
#   25,932 ct x 32
#
# 12:00 liegt im SNAP-Fenster, gehört also zur günstigsten Stufe:
#   Rang    = cheaper + 1        =  0 + 1        = 1
#   Quantil = (cheaper + equal/2) / count * 100
#           = ( 0 + 12) / 96 * 100                = 12,5 %
#
# Ohne Netzgebiet wären es Rang 1 und 16,67 % (equal = 32) – die Wiener Zahlen
# sind die aussagekräftigeren, weil nur sie belegen, dass der Gesamtpreis und
# nicht der Arbeitspreis die Bezugsgröße ist.
PREISRANG_WIEN = {"rang": 1, "quantil": 12.5, "gleich": 24}


@pytest.mark.freeze_time("2026-06-05 10:00:00")  # 12:00 Ortszeit, im SNAP-Fenster
async def test_preisrang_und_quantil_tragen_die_erwarteten_werte(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Beide Kennzahl-Sensoren melden Zustand und Attribute wie hergeleitet.

    Geprüft wird die ganze Kette bis zur Entität: Rechnung im Koordinator,
    Einheit, und die Attribute, die beide Sensoren gemeinsam tragen – damit
    jeder für sich verständlich ist, auch allein im Dashboard.
    """
    await _richte_ein_wien(hass, smarttimes_payload)

    rang = hass.states.get("sensor.smarttimes_strompreishelfer_price_rank_today")
    quantil = hass.states.get(
        "sensor.smarttimes_strompreishelfer_price_quantile_today"
    )

    assert int(rang.state) == PREISRANG_WIEN["rang"]
    assert float(quantil.state) == pytest.approx(PREISRANG_WIEN["quantil"])

    # Der Rang ist dimensionslos, das Quantil eine Prozentangabe.
    assert "unit_of_measurement" not in rang.attributes
    assert quantil.attributes["unit_of_measurement"] == PERCENTAGE

    # Beide tragen dieselbe Einordnung als Attribute.
    for zustand in (rang, quantil):
        assert zustand.attributes["rank"] == PREISRANG_WIEN["rang"]
        assert zustand.attributes["quantile_percent"] == pytest.approx(
            PREISRANG_WIEN["quantil"]
        )
        assert zustand.attributes["interval_count"] == 96
        assert zustand.attributes["cheaper_intervals"] == 0
        assert zustand.attributes["equal_intervals"] == PREISRANG_WIEN["gleich"]
        assert zustand.attributes["quantile_method"] == "midrank"
        assert zustand.attributes["reference"] == "total_price"


@pytest.mark.freeze_time("2026-06-07 10:00:00")  # jenseits der Fixture-Tage
async def test_preisrang_ohne_preise_ist_unbekannt(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Ohne laufendes Intervall stehen beide Sensoren auf ``unknown``.

    Und zwar ohne Attribute: Ein Attributsatz voller ``None`` sähe aus wie eine
    Einordnung, wäre aber keine. In der Praxis ist das der Zustand nach einem
    länger ausgefallenen Abruf.
    """
    await _richte_ein_wien(hass, smarttimes_payload)

    for entity_id in (
        "sensor.smarttimes_strompreishelfer_price_rank_today",
        "sensor.smarttimes_strompreishelfer_price_quantile_today",
    ):
        zustand = hass.states.get(entity_id)
        assert zustand.state == "unknown"
        assert "rank" not in zustand.attributes
