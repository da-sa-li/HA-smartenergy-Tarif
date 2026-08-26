"""Gemeinsame Geräte-Infos und Basisklasse der Untereintrags-Entitäten.

Die Integration legt zwei Sorten von Geräten an:

* **Das Hub-Gerät** – eines je Config-Eintrag, es trägt die Preissensoren und
  den Diagnose-Binary-Sensor.
* **Ein Gerät je „Günstige Stunde"-Untereintrag** – benannt nach dem
  Verbraucher („Boiler", „Wallbox"), es trägt dessen Entitäten.

Beide Geräte-Infos standen früher als wörtlich ausgeschriebene ``DeviceInfo``
in ``sensor.py`` bzw. ``binary_sensor.py``. Seit je Untereintrag **mehrere**
Entitäten entstehen (Binary-Sensor *und* Zeitstempel-Sensor), sind sie hier
zusammengefasst – sonst liefen die Beschreibungen desselben Geräts über zwei
Plattformen hinweg auseinander.
"""

from __future__ import annotations

import logging

# Die Typ-Hinweise nutzen `ConfigEntry` und nicht den Alias
# `SmartTimesConfigEntry` aus `__init__.py`: Jenes Modul importiert von hier
# (`hub_device_info`), ein Rückimport wäre zur Laufzeit ein Zyklus.
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CHEAP_HOURS,
    CONF_CHEAP_MODE,
    CONF_EXACT_HOURS,
    DEFAULT_CHEAP_MODE,
    DEFAULT_EXACT_HOURS,
    DOMAIN,
    documentation_url,
)
from .coordinator import SmartTimesCoordinator
from .jitter import cheap_phase

_LOGGER = logging.getLogger(__name__)


def hub_device_info(entry: ConfigEntry, tariff_name: str) -> DeviceInfo:
    """Geräte-Info des Hub-Geräts (eines je Config-Eintrag)."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"{tariff_name} Strompreishelfer",
        manufacturer="smartENERGY",
        model=tariff_name,
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=documentation_url(tariff_name),
    )


def hub_device_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Registry-ID des Hub-Geräts, oder ``None``, wenn es (noch) fehlt.

    ``async_setup_entry`` legt das Hub-Gerät ausdrücklich an, bevor es an die
    Plattformen weiterreicht – hier sollte also immer eine ID herauskommen.
    Bleibt sie aus, hängen die Untereintrags-Geräte lediglich ungebunden im
    Baum; das ist besser, als sie mit einer unbekannten ID zu verknüpfen (die
    Geräte-Registry lehnt das ab und Home Assistant ließe die Entität dann
    ganz weg).
    """
    geraet = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )
    if geraet is None:
        _LOGGER.warning(
            "Hub-Gerät zu Eintrag %s nicht gefunden; die Günstige-Stunde-Geräte "
            "bleiben ohne Verknüpfung zum Strompreishelfer.",
            entry.entry_id,
        )
        return None
    return geraet.id


def cheap_hour_device_info(
    subentry: ConfigSubentry, tariff_name: str, hub_id: str | None = None
) -> DeviceInfo:
    """Geräte-Info eines „Günstige Stunde"-Untereintrags.

    ``hub_id`` verknüpft das Gerät als „verbunden über" mit dem Hub-Gerät, so
    dass die Zugehörigkeit „Boiler-Sensor gehört zum Strompreishelfer" auf der
    Geräteseite sichtbar wird. Fehlt die ID, bleibt der Schlüssel weg statt
    ``None`` zu setzen – siehe :func:`hub_device_id`.
    """
    info = DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        manufacturer="smartENERGY",
        model=f"{tariff_name} Günstige Stunde",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=documentation_url(tariff_name),
    )
    if hub_id is not None:
        info["via_device_id"] = hub_id
    return info


class CheapHourEntity(CoordinatorEntity[SmartTimesCoordinator]):
    """Basis der Entitäten eines „Günstige Stunde"-Untereintrags.

    Bündelt, was Binary-Sensor und Zeitstempel-Sensor gemeinsam aus dem
    Untereintrag ziehen: die Schaltparameter, den Last-Glättungs-Versatz und
    das Gerät. Die Unterklassen setzen nur noch ihre ``unique_id`` und ihren
    ``translation_key``.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SmartTimesCoordinator,
        subentry: ConfigSubentry,
        hub_id: str | None = None,
    ) -> None:
        """Liest Stundenzahl, Auswahllogik und Jitter-Phase aus dem Untereintrag."""
        super().__init__(coordinator)
        self._cheap_hours: float = subentry.data[CONF_CHEAP_HOURS]
        # Auswahllogik: günstigste Einzelstunden (dürfen zerteilt sein) oder ein
        # zusammenhängender Block „am Stück". Ältere Untereinträge ohne diese
        # Option fallen auf den Standard (Einzelstunden) zurück.
        self._cheap_mode: str = subentry.data.get(CONF_CHEAP_MODE, DEFAULT_CHEAP_MODE)
        # Die eingestellte Stundenzahl exakt einhalten, statt bei
        # Preisgleichstand darüber hinaus zu erweitern? Untereinträge, die die
        # Option noch nicht kannten, haben ihren bisherigen Wert bei der
        # Migration auf Schema-Version 2 ausdrücklich eingetragen (siehe
        # __init__.py); der Rückfall auf die Vorgabe ist nur noch ein Netz.
        self._exact_hours: bool = subentry.data.get(
            CONF_EXACT_HOURS, DEFAULT_EXACT_HOURS
        )
        # Deterministischer, vom Nutzer nicht editierbarer Last-Glättungs-Versatz.
        # Aus der Subentry-ID abgeleitet, damit er stabil und je Sensor
        # gleichverteilt ist (siehe jitter.py).
        self._jitter_phase: float = cheap_phase(subentry.subentry_id)
        # Anzeige-Tarif aus den Koordinatordaten (Modell/Doku-Link je Tarif).
        self._attr_device_info = cheap_hour_device_info(
            subentry, coordinator.data.tariff, hub_id
        )
