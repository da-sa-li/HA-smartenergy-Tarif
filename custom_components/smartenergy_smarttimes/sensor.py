"""Sensoren für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
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
from .const import (
    DOMAIN,
    TARIFF_STATUSES,
    UNIT_CT_PER_KWH,
    UNIT_EUR_PER_KWH,
    UNIT_EUR_PER_MONTH,
    VAT_RATE,
)
from .coordinator import SmartTimesCoordinator, SmartTimesData


@dataclass(frozen=True, kw_only=True)
class SmartTimesSensorDescription(SensorEntityDescription):
    """Beschreibung eines smartTIMES-Sensors."""

    value_fn: Callable[[SmartTimesData], StateType]
    unit: str | None = UNIT_CT_PER_KWH


def _current_value(data: SmartTimesData) -> StateType:
    price = data.current()
    return data.value(price) if price else None


def _current_value_eur(data: SmartTimesData) -> StateType:
    """Gesamtpreis (Arbeitspreis + Nebenkosten) in EUR/kWh."""
    price = data.current()
    return round(data.all_in_value(price) / 100.0, 5) if price else None


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


def _basic_fee(data: SmartTimesData) -> StateType:
    return data.basic_fee()


def _status(data: SmartTimesData) -> StateType:
    return data.status()


SENSORS: tuple[SmartTimesSensorDescription, ...] = (
    SmartTimesSensorDescription(
        key="working_price",
        translation_key="working_price",
        icon="mdi:flash",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_current_value,
    ),
    SmartTimesSensorDescription(
        key="current_price_eur",
        translation_key="current_price_eur",
        icon="mdi:currency-eur",
        unit=UNIT_EUR_PER_KWH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
        value_fn=_current_value_eur,
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
    SmartTimesSensorDescription(
        key="basic_fee",
        translation_key="basic_fee",
        icon="mdi:cash",
        unit=UNIT_EUR_PER_MONTH,
        suggested_display_precision=2,
        value_fn=_basic_fee,
    ),
    SmartTimesSensorDescription(
        key="tariff_status",
        translation_key="tariff_status",
        icon="mdi:meter-electric",
        unit=None,
        device_class=SensorDeviceClass.ENUM,
        options=list(TARIFF_STATUSES),
        value_fn=_status,
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

    def __init__(
        self,
        coordinator: SmartTimesCoordinator,
        entry: SmartTimesConfigEntry,
        description: SmartTimesSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_native_unit_of_measurement = description.unit
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
        """Zusätzliche Attribute für ausgewählte Sensoren."""
        if self.entity_description.key == "tariff_status":
            return self._status_attributes()
        if self.entity_description.key == "current_price_eur":
            return self._all_in_attributes()
        if self.entity_description.key != "working_price":
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
            "basic_fee": data.basic_fee(),
            "basic_fee_unit": data.basic_fee_unit,
            "prices_today": serialise(data.for_day(today)),
            "prices_tomorrow": serialise(data.for_day(tomorrow)),
            "prices": serialise(data.prices),
        }

    def _status_attributes(self) -> dict:
        """Attribute des Tarifzonen-Sensors."""
        data = self.coordinator.data
        next_status, next_start = data.next_status_change()
        return {
            "vat_included": data.include_vat,
            "level_prices": data.level_prices(),
            "next_status": next_status,
            "next_status_start": next_start.isoformat() if next_start else None,
        }

    def _all_in_attributes(self) -> dict:
        """Aufschlüsselung des Gesamtpreises (Arbeitspreis + Nebenkosten)."""
        data = self.coordinator.data
        price = data.current()
        # Nebenkosten anhand des aktuellen Intervalls bestimmen, damit die
        # Aufschlüsselung exakt zum Sensorwert passt.
        moment = price.start if price else None
        working_price = data.value(price) if price else None
        surcharges_total = data.surcharges_total(moment)
        return {
            "vat_included": data.include_vat,
            "vat_rate": VAT_RATE,
            "unit_ct": UNIT_CT_PER_KWH,
            "working_price_ct_kwh": working_price,
            "surcharges_ct_kwh": data.surcharge_breakdown(moment),
            "surcharges_total_ct_kwh": surcharges_total,
            "total_ct_kwh": (
                round(working_price + surcharges_total, 4)
                if working_price is not None
                else None
            ),
        }
