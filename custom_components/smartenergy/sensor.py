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
from .const import (
    DOMAIN,
    UNIT_CT_PER_KWH,
    UNIT_EUR_PER_KWH,
    UNIT_EUR_PER_MONTH,
    VAT_RATE,
    documentation_url,
)
from .coordinator import SmartTimesCoordinator, SmartTimesData
from .grid_fees import is_snap

# Die Entitäten lesen ausschließlich aus dem Koordinator (keine eigenen
# API-Aufrufe, keine schaltenden Aktionen) – eine Drosselung paralleler Updates
# ist daher nicht nötig.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SmartTimesSensorDescription(SensorEntityDescription):
    """Beschreibung eines smartTIMES-Sensors."""

    value_fn: Callable[[SmartTimesData], StateType]
    unit: str | None = UNIT_CT_PER_KWH


def _stats(values: list[float]) -> tuple[StateType, StateType, StateType]:
    """(Durchschnitt, Minimum, Maximum) einer Werteliste."""
    if not values:
        return None, None, None
    return round(sum(values) / len(values), 4), min(values), max(values)


def _today_allin_values(data: SmartTimesData) -> list[float]:
    """Gesamtkosten (ct/kWh) aller heutigen Intervalle."""
    today = dt_util.now().date()
    return [data.all_in_value(p) for p in data.for_day(today)]


def _today_energy_values(data: SmartTimesData) -> list[float]:
    """Arbeitspreise (ct/kWh) aller heutigen Intervalle."""
    today = dt_util.now().date()
    return [data.value(p) for p in data.for_day(today)]


def _current_value(data: SmartTimesData) -> StateType:
    """Reiner Arbeitspreis des aktuellen Intervalls."""
    price = data.current()
    return data.value(price) if price else None


def _current_value_eur(data: SmartTimesData) -> StateType:
    """Gesamtpreis (Arbeitspreis + Nebenkosten) in EUR/kWh."""
    price = data.current()
    return round(data.all_in_value(price) / 100.0, 5) if price else None


def _average_today(data: SmartTimesData) -> StateType:
    """Durchschnittlicher Gesamtpreis (ct/kWh) heute."""
    return _stats(_today_allin_values(data))[0]


def _lowest_today(data: SmartTimesData) -> StateType:
    """Niedrigster Gesamtpreis (ct/kWh) heute."""
    return _stats(_today_allin_values(data))[1]


def _highest_today(data: SmartTimesData) -> StateType:
    """Höchster Gesamtpreis (ct/kWh) heute."""
    return _stats(_today_allin_values(data))[2]


def _basic_fee(data: SmartTimesData) -> StateType:
    """Aktuelle monatliche Grundgebühr (gemäß Brutto-/Netto-Einstellung)."""
    return data.basic_fee()


SENSORS: tuple[SmartTimesSensorDescription, ...] = (
    SmartTimesSensorDescription(
        key="working_price",
        translation_key="working_price",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_current_value,
    ),
    SmartTimesSensorDescription(
        key="current_price_eur",
        translation_key="current_price_eur",
        unit=UNIT_EUR_PER_KWH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
        value_fn=_current_value_eur,
    ),
    SmartTimesSensorDescription(
        key="average_today",
        translation_key="average_today",
        suggested_display_precision=3,
        value_fn=_average_today,
    ),
    SmartTimesSensorDescription(
        key="lowest_today",
        translation_key="lowest_today",
        suggested_display_precision=3,
        value_fn=_lowest_today,
    ),
    SmartTimesSensorDescription(
        key="highest_today",
        translation_key="highest_today",
        suggested_display_precision=3,
        value_fn=_highest_today,
    ),
    SmartTimesSensorDescription(
        key="basic_fee",
        translation_key="basic_fee",
        unit=UNIT_EUR_PER_MONTH,
        suggested_display_precision=2,
        value_fn=_basic_fee,
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
        """Initialisiert den Sensor anhand seiner Beschreibung."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_native_unit_of_measurement = description.unit
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # Anzeige-Tarif aus den Koordinatordaten (nach dem ersten Refresh
        # verfügbar) – bestimmt Gerätename, Modell und Doku-Link je Tarif.
        tariff_name = coordinator.data.tariff
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{tariff_name} Strompreishelfer",
            manufacturer="smartENERGY",
            model=tariff_name,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=documentation_url(tariff_name),
        )

    @property
    def native_value(self) -> StateType:
        """Aktueller Wert des Sensors."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Zusätzliche Attribute für ausgewählte Sensoren."""
        if self.entity_description.key == "current_price_eur":
            return self._all_in_attributes()
        if self.entity_description.key == "working_price":
            return self._working_price_attributes()
        return None

    def _working_price_attributes(self) -> dict:
        """Energiepreis-Vorschau und -Kennzahlen (zur Information)."""
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
        avg, low, high = _stats(_today_energy_values(data))

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
            "average_today": avg,
            "lowest_today": low,
            "highest_today": high,
            "basic_fee": data.basic_fee(),
            "basic_fee_unit": data.basic_fee_unit,
            "prices_today": serialise(data.for_day(today)),
            "prices_tomorrow": serialise(data.for_day(tomorrow)),
            "prices": serialise(data.prices),
        }

    def _all_in_attributes(self) -> dict:
        """Gesamtkosten-Aufschlüsselung, -Vorschau und -Kennzahlen.

        Dieser Sensor reicht allein für Diagramme und Automatisierungen auf
        Basis der gesamten variablen Kosten.
        """
        data = self.coordinator.data
        now = dt_util.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        price = data.current()
        # Nebenkosten anhand des aktuellen Intervalls bestimmen, damit die
        # Aufschlüsselung exakt zum Sensorwert passt.
        moment = price.start if price else now
        working_price = data.value(price) if price else None
        surcharges_total = data.surcharges_total(moment)
        zone = data.grid_zone

        def serialise(prices) -> list[dict]:
            return [
                {
                    "start": p.start.isoformat(),
                    "end": p.end.isoformat(),
                    "price": data.all_in_value(p),
                }
                for p in prices
            ]

        future = [p for p in data.prices if p.start > now]
        next_price = future[0] if future else None
        avg, low, high = _stats(_today_allin_values(data))

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
            "grid_zone": zone.name if zone else None,
            "snap_active": is_snap(moment) if zone else False,
            "average_today": avg,
            "lowest_today": low,
            "highest_today": high,
            "next_price": data.all_in_value(next_price) if next_price else None,
            "next_price_start": (
                next_price.start.isoformat() if next_price else None
            ),
            "prices_today": serialise(data.for_day(today)),
            "prices_tomorrow": serialise(data.for_day(tomorrow)),
            "prices": serialise(data.prices),
        }
