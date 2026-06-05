"""Tests für Einrichtung und Entladen des Config-Eintrags."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient

DOMAIN = "smartenergy"


async def test_setup_and_unload(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
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

    # Sechs Preis-Sensoren, keine Binary-Sensoren (kein Untereintrag angelegt).
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert sum(e.domain == "sensor" for e in entities) == 6
    assert sum(e.domain == "binary_sensor" for e in entities) == 0

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_falls_back_to_data_tariff(
    hass: HomeAssistant, enable_custom_integrations, smartcontrol_payload
):
    # Älterer Eintrag ohne Optionen: Tarif kommt aus data -> smartCONTROL.
    parsed = SmartTimesApiClient._parse(smartcontrol_payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={"tariff": "smartcontrol"},
        options={},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # Anzeige-Tarif stammt aus der Nutzer-Auswahl, nicht aus der API (EPEXSPOTAT).
    assert entry.runtime_data.data.tariff == "smartCONTROL"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
