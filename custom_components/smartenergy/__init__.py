"""Die smartENERGY smartTIMES Integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import SmartTimesApiClient
from .const import (
    API_OPERATOR_DOC_URL,
    CONF_EXACT_HOURS,
    CONF_GRID_ZONE,
    CONF_INCLUDE_VAT,
    CONF_TARIFF,
    DEFAULT_GRID_ZONE,
    DEFAULT_INCLUDE_VAT,
    CONFIG_ENTRY_VERSION,
    DEFAULT_TARIFF,
    DOMAIN,
    SMARTCONTROL_HANDLING_FEE_NET,
    SUBENTRY_TYPE_CHEAP_HOUR,
    TARIFF_API_URLS,
    TARIFF_DISPLAY_NAMES,
    TARIFF_SMARTCONTROL,
)
from .coordinator import SmartTimesCoordinator
from .entity import hub_device_info
from .grid_fees import get_zone

_LOGGER = logging.getLogger(__name__)

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

    integration = await async_get_integration(hass, DOMAIN)
    client = SmartTimesApiClient(
        session,
        api_url,
        integration_version=str(integration.version),
        documentation_url=API_OPERATOR_DOC_URL,
    )
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

    # Das Hub-Gerät ausdrücklich anlegen, bevor die Plattformen laufen. Sensor-
    # und Binary-Sensor-Plattform werden nebenläufig eingerichtet, und die
    # Geräte der „Günstige Stunde“-Untereinträge verweisen per `via_device_id`
    # auf dieses Gerät. Entstünde es weiterhin nur als Nebenprodukt des ersten
    # Preissensors, verlöre der Verweis dieses Rennen – und die Geräte-Registry
    # weist eine unbekannte ID zurück, statt sie still zu verwerfen.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        **hub_device_info(entry, coordinator.data.tariff),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: SmartTimesConfigEntry
) -> bool:
    """Hebt einen älteren Config-Eintrag auf die aktuelle Schema-Version.

    Home Assistant ruft die Funktion auf, solange ``entry.version`` unter
    ``CONFIG_ENTRY_VERSION`` liegt – bei Neueinrichtungen also nie.
    """
    if entry.version > CONFIG_ENTRY_VERSION:
        # Der Eintrag stammt aus einer neueren Fassung der Integration; ihn
        # herunterzustufen kann diese Version nicht leisten.
        return False

    if entry.version == 1:
        _migriere_exact_hours(hass, entry)
        _migriere_gesamtpreis_entitaet(hass, entry)
        hass.config_entries.async_update_entry(entry, version=CONFIG_ENTRY_VERSION)

    return True


def _migriere_exact_hours(
    hass: HomeAssistant, entry: SmartTimesConfigEntry
) -> None:
    """Schreibt Untereinträgen ohne ``exact_hours`` den bisherigen Wert fest.

    Die Vorgabe wechselt mit dieser Schema-Version von "aus" auf "ein".
    Untereinträge, die vor Einführung der Option angelegt wurden, führen den
    Schlüssel nicht und würden die neue Vorgabe erben – ihr Schaltverhalten
    änderte sich damit ungefragt. Der ausdrückliche Eintrag hält sie beim Alten;
    umstellen kann man sie weiterhin von Hand.
    """
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_CHEAP_HOUR:
            continue
        if CONF_EXACT_HOURS in subentry.data:
            continue
        hass.config_entries.async_update_subentry(
            entry,
            subentry,
            data={**subentry.data, CONF_EXACT_HOURS: False},
        )


def _migriere_gesamtpreis_entitaet(
    hass: HomeAssistant, entry: SmartTimesConfigEntry
) -> None:
    """Zieht die Gesamtpreis-Entität auf ihren neuen Schlüssel um.

    Der Beschreibungs-Schlüssel hieß ``current_price_eur``, solange sich der
    Sensor von den ct-Geschwistern abheben musste. Seit alle Preissensoren
    EUR/kWh liefern, heißt er ``total_price``.

    Die ``unique_id`` wird dabei **an Ort und Stelle** umgeschrieben. Die
    Entität behält so ihren Registry-Eintrag samt Historie; ohne diesen Schritt
    legte Home Assistant sie unter der neuen ``unique_id`` neu an und ließe die
    alte als verwaisten Eintrag zurück.
    """
    registry = er.async_get(hass)
    alte_unique_id = f"{entry.entry_id}_current_price_eur"
    entity_id = registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, alte_unique_id
    )
    if entity_id is None:
        # Nichts umzuziehen – etwa, weil der Nutzer die Entität gelöscht hat.
        return

    registry.async_update_entity(
        entity_id, new_unique_id=f"{entry.entry_id}_total_price"
    )

    _migriere_gesamtpreis_entity_id(registry, entity_id)


def _migriere_gesamtpreis_entity_id(
    registry: er.EntityRegistry, entity_id: str
) -> None:
    """Streicht das ``_eur_kwh`` aus der Entity-ID der Gesamtpreis-Entität.

    Der Sensor hieß „Gesamtpreis (EUR/kWh)“; aus dem Zusatz wurde bei der
    erstmaligen Anlage die Entity-ID abgeleitet. Ohne diesen Schritt behielten
    Bestandsinstallationen dauerhaft eine andere Entity-ID als
    Neuinstallationen, und Doku und Wiki könnten keine einheitliche nennen.

    Das ist der einzige Schritt der Migration, den Nutzer merken: Wer die alte
    Entity-ID in Automatisierungen, Vorlagen oder Dashboards referenziert, muss
    sie anpassen.
    """
    suffix = "_eur_kwh"
    if not entity_id.endswith(suffix):
        # Von Hand vergeben oder bereits umgezogen – nicht anfassen.
        return

    neue_entity_id = entity_id.removesuffix(suffix)
    if registry.async_get(neue_entity_id) is not None:
        # Der Name ist belegt. Eine Kollision aufzulösen hieße, eine fremde
        # Entität zu verschieben; die alte ID zu behalten ist das kleinere Übel.
        _LOGGER.warning(
            "Entity-ID %s ist bereits vergeben; %s behält seine bisherige ID.",
            neue_entity_id,
            entity_id,
        )
        return

    registry.async_update_entity(entity_id, new_entity_id=neue_entity_id)
    _LOGGER.info(
        "Gesamtpreis-Sensor von %s nach %s umbenannt (einheitliche Entity-ID "
        "für Bestands- und Neuinstallationen).",
        entity_id,
        neue_entity_id,
    )


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
