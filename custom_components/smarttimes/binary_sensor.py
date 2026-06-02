"""Binary-Sensoren „Günstige Stunde" für die smartTIMES Integration.

Jeder Sensor markiert, ob das aktuelle Intervall zu den günstigsten Stunden des
Tages zählt – gemessen an den **gesamten variablen Kosten** (Arbeitspreis +
Abgaben + Netzentgelte inkl. SNAP). Die Anzahl günstiger Stunden wird je
Untereintrag (Config Subentry) festgelegt, sodass pro Verbraucher ein eigener
Sensor mit eigener Stundenzahl möglich ist (z. B. Boiler 4 h, Wallbox 8 h).
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import SmartTimesConfigEntry
from .const import (
    CONF_CHEAP_HOURS,
    CONF_CHEAP_MODE,
    DEFAULT_CHEAP_MODE,
    DOMAIN,
    JITTER_ON_MAX_SECONDS,
    SUBENTRY_TYPE_CHEAP_HOUR,
    UNIT_CT_PER_KWH,
)
from .coordinator import SmartTimesCoordinator
from .jitter import cheap_phase


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTimesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Richtet je Untereintrag einen „Günstige Stunde"-Binary-Sensor ein."""
    coordinator = entry.runtime_data
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_CHEAP_HOUR:
            continue
        async_add_entities(
            [CheapHourBinarySensor(coordinator, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class CheapHourBinarySensor(
    CoordinatorEntity[SmartTimesCoordinator], BinarySensorEntity
):
    """`on`, wenn die laufende Viertelstunde zu den günstigsten des Tages zählt."""

    _attr_has_entity_name = True
    _attr_translation_key = "cheap_hour"
    _attr_icon = "mdi:cash-clock"

    def __init__(
        self,
        coordinator: SmartTimesCoordinator,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)
        self._cheap_hours: float = subentry.data[CONF_CHEAP_HOURS]
        # Auswahllogik: günstigste Einzelstunden (dürfen zerteilt sein) oder ein
        # zusammenhängender Block „am Stück". Ältere Untereinträge ohne diese
        # Option fallen auf den Standard (Einzelstunden) zurück.
        self._cheap_mode: str = subentry.data.get(CONF_CHEAP_MODE, DEFAULT_CHEAP_MODE)
        # Deterministischer, vom Nutzer nicht editierbarer Last-Glättungs-Versatz.
        # Aus der Subentry-ID abgeleitet, damit er stabil und je Sensor
        # gleichverteilt ist (siehe jitter.py).
        self._jitter_phase: float = cheap_phase(subentry.subentry_id)
        self._attr_unique_id = f"{subentry.subentry_id}_cheap_hour"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="smartENERGY",
            model="smartTIMES Günstige Stunde",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.smartenergy.at/api-schnittstellen-smarttimes",
        )

    @property
    def is_on(self) -> bool | None:
        """Ob der aktuelle Zeitpunkt im (gejitterten) günstigen Fenster liegt."""
        data = self.coordinator.data
        now = dt_util.now()
        # Ohne Preisabdeckung für „jetzt" ist der Zustand unbekannt.
        if data.current(now) is None:
            return None
        return data.is_cheap_now(
            now, self._cheap_hours, self._jitter_phase, self._cheap_mode
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Schwellwert, günstige Intervalle, gejitterte Fenster und nächster Start."""
        data = self.coordinator.data
        now = dt_util.now()
        today = now.date()
        price = data.current(now)
        cheap = data.cheap_intervals(today, self._cheap_hours, self._cheap_mode)
        windows = data.jittered_cheap_windows(
            today, self._cheap_hours, self._jitter_phase, self._cheap_mode
        )
        next_on = data.next_cheap_on(
            now, self._cheap_hours, self._jitter_phase, self._cheap_mode
        )

        def current_price() -> StateType:
            return data.all_in_value(price) if price else None

        return {
            "cheap_hours": self._cheap_hours,
            "cheap_mode": self._cheap_mode,
            "threshold_ct_kwh": data.cheap_cutoff(
                today, self._cheap_hours, self._cheap_mode
            ),
            "current_price_ct_kwh": current_price(),
            "unit_ct": UNIT_CT_PER_KWH,
            "vat_included": data.include_vat,
            # Last-Glättung: konstanter Einschalt-Versatz dieses Sensors in
            # Sekunden (deterministisch, vom Nutzer nicht änderbar).
            "jitter_offset_seconds": round(
                self._jitter_phase * JITTER_ON_MAX_SECONDS
            ),
            "next_cheap_start": next_on.isoformat() if next_on else None,
            "cheap_intervals": [
                {
                    "start": p.start.isoformat(),
                    "end": p.end.isoformat(),
                    "price": data.all_in_value(p),
                }
                for p in cheap
            ],
            # Tatsächliche, gejitterte Schaltfenster (so, wie der Sensor schaltet).
            # ``soft_end``: Blockende gleichstandsbedingt gekappt (kein Ausgreifen
            # in die nächste Preiszone).
            "cheap_windows": [
                {
                    "on": on_time.isoformat(),
                    "off": off_time.isoformat(),
                    "soft_end": soft_end,
                }
                for on_time, off_time, soft_end in windows
            ],
        }
