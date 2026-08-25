"""Sensoren für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

import logging
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
    UNIT_EUR_PER_KWH,
    UNIT_EUR_PER_MONTH,
    VAT_RATE,
    documentation_url,
    to_eur,
)
from .coordinator import SmartTimesCoordinator, SmartTimesData
from .grid_fees import is_snap

_LOGGER = logging.getLogger(__name__)

# Einheit, in der die API die Grundgebühr meldet. Angezeigt wird stattdessen die
# eingedeutschte Fassung UNIT_EUR_PER_MONTH; weicht die API davon ab, wird
# gewarnt (siehe async_setup_entry).
API_BASIC_FEE_UNIT = "EUR/month"

# Die Entitäten lesen ausschließlich aus dem Koordinator (keine eigenen
# API-Aufrufe, keine schaltenden Aktionen) – eine Drosselung paralleler Updates
# ist daher nicht nötig.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SmartTimesSensorDescription(SensorEntityDescription):
    """Beschreibung eines smartTIMES-Sensors."""

    value_fn: Callable[[SmartTimesData], StateType]
    unit: str | None = UNIT_EUR_PER_KWH


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
    """Reiner Arbeitspreis des aktuellen Intervalls (EUR/kWh)."""
    price = data.current()
    return to_eur(data.value(price)) if price else None


def _current_total_value(data: SmartTimesData) -> StateType:
    """Gesamtpreis (Arbeitspreis + Nebenkosten) in EUR/kWh."""
    price = data.current()
    return to_eur(data.all_in_value(price)) if price else None


def _average_today(data: SmartTimesData) -> StateType:
    """Durchschnittlicher Gesamtpreis (EUR/kWh) heute."""
    return to_eur(_stats(_today_allin_values(data))[0])


def _lowest_today(data: SmartTimesData) -> StateType:
    """Niedrigster Gesamtpreis (EUR/kWh) heute."""
    return to_eur(_stats(_today_allin_values(data))[1])


def _highest_today(data: SmartTimesData) -> StateType:
    """Höchster Gesamtpreis (EUR/kWh) heute."""
    return to_eur(_stats(_today_allin_values(data))[2])


def _basic_fee(data: SmartTimesData) -> StateType:
    """Aktuelle monatliche Grundgebühr (gemäß Brutto-/Netto-Einstellung)."""
    return data.basic_fee()


SENSORS: tuple[SmartTimesSensorDescription, ...] = (
    SmartTimesSensorDescription(
        key="working_price",
        translation_key="working_price",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
        value_fn=_current_value,
    ),
    SmartTimesSensorDescription(
        key="total_price",
        translation_key="total_price",
        unit=UNIT_EUR_PER_KWH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
        value_fn=_current_total_value,
    ),
    SmartTimesSensorDescription(
        key="average_today",
        translation_key="average_today",
        suggested_display_precision=5,
        value_fn=_average_today,
    ),
    SmartTimesSensorDescription(
        key="lowest_today",
        translation_key="lowest_today",
        suggested_display_precision=5,
        value_fn=_lowest_today,
    ),
    SmartTimesSensorDescription(
        key="highest_today",
        translation_key="highest_today",
        suggested_display_precision=5,
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


def _is_available(description: SmartTimesSensorDescription, data: SmartTimesData) -> bool:
    """Ob der Tarif die Datengrundlage für diesen Sensor überhaupt liefert.

    Betrifft bislang nur die Grundgebühr: smartTIMES liefert den optionalen
    ``basicFee``-Block der API, smartCONTROL nicht. Ohne ihn stünde der Sensor
    dauerhaft auf „unbekannt" und sähe aus wie ein Defekt.
    """
    if description.key == "basic_fee":
        return bool(data.basic_fees)
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTimesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Richtet die smartTIMES-Sensoren ein.

    Die Auswahl stützt sich auf die Koordinatordaten, die hier bereits
    vorliegen: ``async_config_entry_first_refresh()`` läuft in ``__init__.py``
    vor dem Weiterreichen an die Plattformen. Liefert die API später doch eine
    Grundgebühr, erscheint der Sensor nach einem Neuladen des Eintrags.
    """
    coordinator = entry.runtime_data
    data = coordinator.data

    if data.basic_fee_unit is not None and data.basic_fee_unit != API_BASIC_FEE_UNIT:
        # Die Anzeige-Einheit ist bewusst eingedeutscht ("EUR/Monat" statt des
        # von der API gelieferten "EUR/month"). Wechselt die API die Einheit,
        # zeigte der Sensor sonst stillschweigend eine falsche an.
        _LOGGER.warning(
            "Die smartENERGY-API meldet die Grundgebühr in '%s', erwartet wurde "
            "'%s'. Der Sensor zeigt weiterhin '%s' an – dieser Wert könnte damit "
            "nicht mehr passen.",
            data.basic_fee_unit,
            API_BASIC_FEE_UNIT,
            UNIT_EUR_PER_MONTH,
        )

    async_add_entities(
        SmartTimesSensor(coordinator, entry, description)
        for description in SENSORS
        if _is_available(description, data)
    )


class SmartTimesSensor(CoordinatorEntity[SmartTimesCoordinator], SensorEntity):
    """Ein einzelner smartTIMES-Preissensor."""

    entity_description: SmartTimesSensorDescription
    _attr_has_entity_name = True
    # Preisvorschau-Listen sind minütlich neu berechnete, rein
    # zukunftsgerichtete Daten - Recorder-History bringt hier keinen Mehrwert
    # und die Listen überschreiten sonst die 16-KiB-Attributgrenze.
    _unrecorded_attributes = frozenset({"prices_today", "prices_tomorrow"})

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
        if self.entity_description.key == "total_price":
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
                    "price": to_eur(data.value(p)),
                }
                for p in prices
            ]

        current = data.current(now)
        future = [p for p in data.prices if p.start > now]
        next_price = future[0] if future else None
        avg, low, high = _stats(_today_energy_values(data))

        # Achtung, bewusste Namensgebung: Sämtliche Kennzahlen dieses Sensors
        # beziehen sich auf den reinen ARBEITSPREIS. Die gleichnamigen Sensoren
        # (average_today & Co.) und die Attribute des Gesamtpreis-Sensors meinen
        # dagegen den GESAMTPREIS inklusive Nebenkosten. Früher trugen beide
        # dieselben Namen, was sich am Wert nicht erkennen ließ – deshalb führen
        # sie hier "working_price" im Namen.
        return {
            "tariff": data.tariff,
            "unit": UNIT_EUR_PER_KWH,
            # Einheit, in der die API liefert und in der der Coordinator rechnet.
            # Die Entitäten geben EUR/kWh aus (siehe const.to_eur).
            "source_unit": data.unit,
            "interval_minutes": data.interval_minutes,
            "vat_included": data.include_vat,
            "current_start": current.start.isoformat() if current else None,
            "current_end": current.end.isoformat() if current else None,
            "next_working_price": (
                to_eur(data.value(next_price)) if next_price else None
            ),
            "next_working_price_start": (
                next_price.start.isoformat() if next_price else None
            ),
            "average_working_price_today": to_eur(avg),
            "lowest_working_price_today": to_eur(low),
            "highest_working_price_today": to_eur(high),
            "basic_fee": data.basic_fee(),
            "basic_fee_unit": data.basic_fee_unit,
            "prices_today": serialise(data.for_day(today)),
            "prices_tomorrow": serialise(data.for_day(tomorrow)),
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
                    "price": to_eur(data.all_in_value(p)),
                }
                for p in prices
            ]

        future = [p for p in data.prices if p.start > now]
        next_price = future[0] if future else None
        avg, low, high = _stats(_today_allin_values(data))

        return {
            "vat_included": data.include_vat,
            "vat_rate": VAT_RATE,
            "unit": UNIT_EUR_PER_KWH,
            # Einheit der API bzw. des Coordinators – siehe Arbeitspreis-Sensor.
            "source_unit": data.unit,
            "working_price_eur_kwh": to_eur(working_price),
            "surcharges_eur_kwh": {
                key: to_eur(wert)
                for key, wert in data.surcharge_breakdown(moment).items()
            },
            "surcharges_total_eur_kwh": to_eur(surcharges_total),
            "total_eur_kwh": (
                to_eur(round(working_price + surcharges_total, 4))
                if working_price is not None
                else None
            ),
            "grid_zone": zone.name if zone else None,
            "snap_active": is_snap(moment) if zone else False,
            "average_today": to_eur(avg),
            "lowest_today": to_eur(low),
            "highest_today": to_eur(high),
            "next_price": (
                to_eur(data.all_in_value(next_price)) if next_price else None
            ),
            "next_price_start": (
                next_price.start.isoformat() if next_price else None
            ),
            "prices_today": serialise(data.for_day(today)),
            "prices_tomorrow": serialise(data.for_day(tomorrow)),
        }
