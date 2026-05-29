"""Die smartENERGY smartTIMES Integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SmartTimesApiClient
from .const import (
    CONF_GRID_ZONE,
    CONF_INCLUDE_VAT,
    DEFAULT_GRID_ZONE,
    DEFAULT_INCLUDE_VAT,
)
from .coordinator import SmartTimesCoordinator
from .grid_fees import get_zone

PLATFORMS: list[Platform] = [Platform.SENSOR]

type SmartTimesConfigEntry = ConfigEntry[SmartTimesCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: SmartTimesConfigEntry
) -> bool:
    """Richtet smartTIMES anhand eines Config-Eintrags ein."""
    session = async_get_clientsession(hass)
    client = SmartTimesApiClient(session)
    include_vat = entry.options.get(
        CONF_INCLUDE_VAT,
        entry.data.get(CONF_INCLUDE_VAT, DEFAULT_INCLUDE_VAT),
    )
    grid_zone = get_zone(entry.options.get(CONF_GRID_ZONE, DEFAULT_GRID_ZONE))

    coordinator = SmartTimesCoordinator(hass, entry, client, include_vat, grid_zone)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SmartTimesConfigEntry
) -> bool:
    """Entlädt einen Config-Eintrag."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: SmartTimesConfigEntry
) -> None:
    """Lädt die Integration neu, wenn die Optionen geändert wurden."""
    await hass.config_entries.async_reload(entry.entry_id)
