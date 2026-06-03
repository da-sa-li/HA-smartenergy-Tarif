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
    CONF_TARIFF,
    DEFAULT_GRID_ZONE,
    DEFAULT_INCLUDE_VAT,
    DEFAULT_TARIFF,
    SMARTCONTROL_HANDLING_FEE_NET,
    TARIFF_API_URLS,
    TARIFF_DISPLAY_NAMES,
    TARIFF_SMARTCONTROL,
)
from .coordinator import SmartTimesCoordinator
from .grid_fees import get_zone

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type SmartTimesConfigEntry = ConfigEntry[SmartTimesCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: SmartTimesConfigEntry
) -> bool:
    """Richtet die Integration (smartTIMES oder smartCONTROL) ein."""
    session = async_get_clientsession(hass)

    # Tarif aus den Optionen (Fallback auf data, dann Default smartTIMES – deckt
    # bestehende Einträge ohne CONF_TARIFF ab, daher keine Migration nötig).
    tariff = entry.options.get(
        CONF_TARIFF, entry.data.get(CONF_TARIFF, DEFAULT_TARIFF)
    )
    api_url = TARIFF_API_URLS.get(tariff, TARIFF_API_URLS[DEFAULT_TARIFF])
    tariff_name = TARIFF_DISPLAY_NAMES.get(
        tariff, TARIFF_DISPLAY_NAMES[DEFAULT_TARIFF]
    )
    # Abwicklungsgebühr (netto, ct/kWh) nur bei smartCONTROL.
    handling_fee_net = (
        SMARTCONTROL_HANDLING_FEE_NET if tariff == TARIFF_SMARTCONTROL else 0.0
    )

    client = SmartTimesApiClient(session, api_url)
    include_vat = entry.options.get(
        CONF_INCLUDE_VAT,
        entry.data.get(CONF_INCLUDE_VAT, DEFAULT_INCLUDE_VAT),
    )
    grid_zone = get_zone(entry.options.get(CONF_GRID_ZONE, DEFAULT_GRID_ZONE))

    coordinator = SmartTimesCoordinator(
        hass,
        entry,
        client,
        include_vat,
        grid_zone,
        handling_fee_net=handling_fee_net,
        tariff_name=tariff_name,
    )
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
