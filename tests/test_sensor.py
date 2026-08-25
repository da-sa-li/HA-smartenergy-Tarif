"""Tests für die Sensor-Plattform.

Geprüft wird, welche Entitäten ein Tarif überhaupt hervorbringt. Die
Grundgebühr ist der einzige Sensor, dessen Datengrundlage optional ist:
smartTIMES liefert den ``basicFee``-Block der API, smartCONTROL nicht.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient

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

    Angezeigt wird bewusst das eingedeutschte „EUR/Monat" statt des von der API
    gelieferten „EUR/month". Wechselte die API auf z. B. „EUR/year", zeigte der
    Sensor sonst stillschweigend eine falsche Einheit an.
    """
    payload = dict(smarttimes_payload)
    payload["basicFee"] = dict(payload["basicFee"], unit="EUR/year")

    await _richte_ein(hass, payload, "smarttimes")

    assert "EUR/year" in caplog.text
    assert "EUR/Monat" in caplog.text


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
            assert beschreibung.unit == UNIT_EUR_PER_MONTH
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
