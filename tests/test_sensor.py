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
        "current_price_eur",
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
