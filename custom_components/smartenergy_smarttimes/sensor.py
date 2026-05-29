"""Sensoren für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import SmartTimesConfigEntry
from .const import DOMAIN, UNIT_CT_PER_KWH
from .coordinator import SmartTimesCoordinator, SmartTimesData


@dataclass(frozen=True, kw_only=True)
class SmartTimesSensorDescription(SensorEntityDescription):
    """Beschreibung eines smartTIMES-Sensors."""

    value_fn: Callable[[SmartTimesData], StateType]


def _current_value(data: SmartTimesData) -> StateType:
    price = data.current()
    return data.value(price) if price else None


def _today_values(data: SmartTimesData) -> list[float]:
    today = dt_util.now().date()
    return [data.value(p) for p in data.for_day(today)]


def _average_today(data: SmartTimesData) -> StateType:
    values = _today_values(data)
    return round(sum(values) / len(values), 4) if values else None


def _lowest_today(data: SmartTimesData) -> StateType:
    values = _today_values(data)
    return min(values) if values else None


def _highest_today(data: SmartTimesData) -> StateType:
    values = _today_values(data)
    return max(values) if values else None


SENSORS: tuple[SmartTimesSensorDescription, ...] = (
    SmartTimesSensorDescription(
        key="current_price",
        translation_key="current_price",
        icon="mdi:flash",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_current_value,
    ),
    SmartTimesSensorDescription(
        key="average_today",
        translation_key="average_today",
        icon="mdi:chart-line",
        suggested_display_precision=3,
        value_fn=_average_today,
    ),
    SmartTimesSensorDescription(
        key="lowest_today",
        translation_key="lowest_today",
        icon="mdi:trending-down",
        suggested_display_precision=3,
        value_fn=_lowest_today,
    ),
    SmartTimesSensorDescription(
        key="highest_today",
        translation_key="highest_today",
        icon="mdi:trending-up",
        suggested_display_precision=3,
        value_fn=_highest_today,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTimesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Richtet die smartTIMES-Sensoren ein."""
    coordinator = entry.runtime_data
    async_add_entities(
        SmartTimesSensor(coordinator, entry, description) for description in SENSORS
    )


class SmartTimesSensor(CoordinatorEntity[SmartTimesCoordinator], SensorEntity):
    """Ein einzelner smartTIMES-Preissensor."""

    entity_description: SmartTimesSensorDescription
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UNIT_CT_PER_KWH

    def __init__(
        self,
        coordinator: SmartTimesCoordinator,
        entry: SmartTimesConfigEntry,
        description: SmartTimesSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="smartENERGY smartTIMES",
            manufacturer="smartENERGY",
            model="smartTIMES",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.smartenergy.at/api-schnittstellen-smarttimes",
        )

    @property
    def native_value(self) -> StateType:
        """Aktueller Wert des Sensors."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Zusätzliche Attribute – nur am Sensor für den aktuellen Preis."""
        if self.entity_description.key != "current_price":
            return None

        data = self.coordinator.data
        now = dt_util.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        def serialise(prices) -> list[dict]:
            return [
                {
                    "start": p.start.isoformat(),
                    "end": p.end.isoformat(),
                    "price": data.value(p),
                }
                for p in prices
            ]

        current = data.current(now)
        future = [p for p in data.prices if p.start > now]
        next_price = future[0] if future else None

        return {
            "tariff": data.tariff,
            "unit": data.unit,
            "interval_minutes": data.interval_minutes,
            "vat_included": data.include_vat,
            "current_start": current.start.isoformat() if current else None,
            "current_end": current.end.isoformat() if current else None,
            "next_price": data.value(next_price) if next_price else None,
            "next_price_start": (
                next_price.start.isoformat() if next_price else None
            ),
            "average_today": _average_today(data),
            "lowest_today": _lowest_today(data),
            "highest_today": _highest_today(data),
            "prices_today": serialise(data.for_day(today)),
            "prices_tomorrow": serialise(data.for_day(tomorrow)),
            "prices": serialise(data.prices),
        }
