"""Sensoren für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import SmartTimesConfigEntry
from .const import (
    SUBENTRY_TYPE_CHEAP_HOUR,
    UNIT_EUR_PER_KWH,
    UNIT_EUR_PER_MONTH,
    VAT_RATE,
    to_eur,
)
from .coordinator import SmartTimesCoordinator, SmartTimesData
from .entity import CheapHourEntity, hub_device_id, hub_device_info
from .grid_fees import is_snap

_LOGGER = logging.getLogger(__name__)

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


def _tagesbezug(day: date | None) -> date:
    """Der übergebene Kalendertag, sonst der heutige.

    ``day`` durchzureichen ist wichtig, wo der Aufrufer seinen Tag bereits
    erfasst hat: Ein zweiter Blick auf die Uhr kann auf die andere Seite des
    Tageswechsels fallen, und dann beschriebe ``average_today`` einen anderen
    Tag als die Preisvorschau daneben. Die eigenständigen Kennzahl-Sensoren
    haben keinen solchen Bezugspunkt und fragen weiterhin selbst.
    """
    return day if day is not None else dt_util.now().date()


def _today_allin_values(data: SmartTimesData, day: date | None = None) -> list[float]:
    """Gesamtkosten (ct/kWh) aller Intervalle eines Tages (Standard: heute)."""
    return [data.all_in_value(p) for p in data.for_day(_tagesbezug(day))]


def _today_energy_values(data: SmartTimesData, day: date | None = None) -> list[float]:
    """Arbeitspreise (ct/kWh) aller Intervalle eines Tages (Standard: heute)."""
    return [data.value(p) for p in data.for_day(_tagesbezug(day))]


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


def _price_rank_today(data: SmartTimesData) -> StateType:
    """Rang des laufenden Intervalls unter den Gesamtpreisen des Tages."""
    einordnung = data.price_rank()
    return einordnung.rank if einordnung else None


def _price_quantile_today(data: SmartTimesData) -> StateType:
    """Quantil des laufenden Intervalls (Prozent) unter den Tagespreisen."""
    einordnung = data.price_rank()
    return einordnung.quantile if einordnung else None


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
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
        value_fn=_average_today,
    ),
    SmartTimesSensorDescription(
        key="lowest_today",
        translation_key="lowest_today",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
        value_fn=_lowest_today,
    ),
    SmartTimesSensorDescription(
        key="highest_today",
        translation_key="highest_today",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
        value_fn=_highest_today,
    ),
    SmartTimesSensorDescription(
        key="price_rank_today",
        translation_key="price_rank_today",
        # Eine dimensionslose Ordnungszahl – `unit` wird ausdrücklich auf None
        # gesetzt, weil die Vorgabe der Beschreibung EUR/kWh lautet.
        unit=None,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_price_rank_today,
    ),
    SmartTimesSensorDescription(
        key="price_quantile_today",
        translation_key="price_quantile_today",
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_price_quantile_today,
    ),
    SmartTimesSensorDescription(
        key="basic_fee",
        translation_key="basic_fee",
        unit=UNIT_EUR_PER_MONTH,
        suggested_display_precision=2,
        value_fn=_basic_fee,
    ),
)


def _hat_datengrundlage(
    description: SmartTimesSensorDescription, data: SmartTimesData
) -> bool:
    """Ob der Tarif die Datengrundlage für diesen Sensor überhaupt liefert.

    Betrifft bislang nur die Grundgebühr: smartTIMES liefert den optionalen
    ``basicFee``-Block der API, smartCONTROL nicht. Ohne ihn stünde der Sensor
    dauerhaft auf „unbekannt“ und sähe aus wie ein Defekt.

    Entscheidet über das **Anlegen** der Entität, nicht über ihre
    Verfügbarkeit zur Laufzeit – deshalb nicht ``_is_available``: Der frühere
    Name legte ein ``available``-Property nahe, das minütlich mitliefe. Die
    Auswertung geschieht stattdessen genau einmal, in ``async_setup_entry``.
    Liefert die API die Grundgebühr erst später, erscheint der Sensor daher
    erst nach einem Neuladen des Eintrags; verschwindet sie, bleibt er stehen
    und meldet ``unbekannt``.
    """
    if description.key == "basic_fee":
        return bool(data.basic_fees)
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTimesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Richtet die smartTIMES-Sensoren ein.

    Die Auswahl stützt sich auf die Koordinatordaten, die hier bereits
    vorliegen: ``async_config_entry_first_refresh()`` läuft in ``__init__.py``
    vor dem Weiterreichen an die Plattformen. Liefert die API später doch eine
    Grundgebühr, erscheint der Sensor nach einem Neuladen des Eintrags.
    """
    coordinator = entry.runtime_data
    data = coordinator.data

    if data.basic_fee_unit is not None and data.basic_fee_unit != UNIT_EUR_PER_MONTH:
        # Die Anzeige-Einheit ist fest hinterlegt. Wechselte die API auf eine
        # andere (etwa EUR/year), zeigte der Sensor sonst stillschweigend eine
        # falsche an.
        _LOGGER.warning(
            "Die smartENERGY-API meldet die Grundgebühr in '%s'. Der Sensor "
            "zeigt sie weiterhin als '%s' an – dieser Wert könnte damit nicht "
            "mehr passen.",
            data.basic_fee_unit,
            UNIT_EUR_PER_MONTH,
        )

    async_add_entities(
        SmartTimesSensor(coordinator, entry, description)
        for description in SENSORS
        if _hat_datengrundlage(description, data)
    )

    # Gerät, an dem die Untereintrags-Geräte als „verbunden über“ hängen.
    # `__init__.async_setup_entry` hat es vor dem Weiterreichen angelegt.
    hub_id = hub_device_id(hass, entry)
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_CHEAP_HOUR:
            continue
        # Ein Aufruf je Untereintrag: `config_subentry_id` gilt für die ganze
        # Charge und bindet Gerät wie Entität an genau diesen Untereintrag.
        async_add_entities(
            [NextCheapStartSensor(coordinator, subentry, hub_id)],
            config_subentry_id=subentry.subentry_id,
        )


class NextCheapStartSensor(CheapHourEntity, SensorEntity):
    """Nächster (gejitterter) Einschaltzeitpunkt des Untereintrags.

    Bewusst eine eigene Entität und nicht nur das Attribut ``next_cheap_start``
    am Binary-Sensor: Der ``time``-Trigger von Home Assistant nimmt unter ``at:``
    ausschließlich Entitäten mit ``device_class: timestamp``. Ein Attribut lässt
    sich dort nicht referenzieren, weshalb „30 Minuten vor dem günstigen Fenster
    vorheizen“ bisher einen Template-Sensor brauchte.

    Der Wert ist ``unknown``, solange kein nächstes Fenster bekannt ist – etwa
    spät abends, bevor die Preise für den Folgetag veröffentlicht sind. Ein
    ``time``-Trigger feuert dann schlicht nicht.
    """

    _attr_translation_key = "next_cheap_start"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # Weder `state_class` noch Einheit: Für Zeitstempel gibt es keine
    # Langzeitstatistik, und eine Einheit weist Home Assistant zurück. Deshalb
    # steht dieser Sensor auch nicht in SENSORS – die dortigen Beschreibungen
    # sind durchweg Preissensoren in EUR/kWh.

    def __init__(
        self,
        coordinator: SmartTimesCoordinator,
        subentry: ConfigSubentry,
        hub_id: str | None = None,
    ) -> None:
        """Setzt die eindeutige ID; alles Weitere kommt aus der Basisklasse."""
        super().__init__(coordinator, subentry, hub_id)
        self._attr_unique_id = f"{subentry.subentry_id}_next_cheap_start"

    @property
    def native_value(self) -> datetime | None:
        """Nächster Einschaltzeitpunkt (zeitzonenbewusst) oder ``None``.

        Der Wert enthält den Last-Glättungs-Versatz dieses Untereintrags bereits
        und ist sekundengenau – in dieser Auflösung nimmt ihn der ``time``-Trigger
        unter ``at:`` entgegen.

        Der zugehörige „Günstige Stunde“-Binary-Sensor erreicht diese Auflösung
        **nicht**: Er wird nur ausgewertet, wenn der Koordinator rechnet, und der
        tickt im Minutentakt (``RECALC_INTERVAL_MINUTES``). Er geht also bis zu
        eine Minute *nach* diesem Zeitstempel auf ``on``. Für die Last-Glättung
        genügt das – eine Streuung über ``JITTER_SPAN_SECONDS`` bleibt auch auf
        einem Minutenraster eine Streuung über zehn Minuten. Wer beides in einer
        Automatisierung verknüpft, darf den Binary-Sensor zum Zeitpunkt dieses
        Zeitstempels aber noch nicht als ``on`` voraussetzen.
        """
        return self.coordinator.data.next_cheap_on(
            dt_util.now(),
            self._cheap_hours,
            self._jitter_phase,
            self._cheap_mode,
            self._exact_hours,
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
        self._attr_device_info = hub_device_info(entry, coordinator.data.tariff)

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
        if self.entity_description.key in ("price_rank_today", "price_quantile_today"):
            return self._rank_attributes()
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
        avg, low, high = _stats(_today_energy_values(data, today))

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
            # Unterscheidet "noch nicht veröffentlicht" von "leer": Beides
            # ergibt sonst dieselbe leere Liste. Anders als die Liste selbst
            # wird dieser Wert vom Recorder mitgeschrieben, taugt also auch
            # zur Frage "ab wann waren die Preise da".
            "prices_tomorrow_valid": data.has_prices_for(tomorrow),
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

        # Ein einziger Blick auf die Uhr für den ganzen Attributsatz – oben
        # `now`, hier und bei den Tageskennzahlen durchgereicht. Jeder eigene
        # `dt_util.now()`-Aufruf könnte auf die andere Seite eines Intervall-
        # oder Tageswechsels fallen, und dann beschriebe die Aufschlüsselung ein
        # anderes Intervall als die Vorschau daneben.
        price = data.current(now)
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
        avg, low, high = _stats(_today_allin_values(data, today))

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
            # Dieselbe Rechnung wie der Sensorwert (`native_value`), nicht die
            # Summe der beiden Attribute darüber: Jene addierte zwei bereits
            # gerundete Bruttowerte, während der Zustand netto summiert und die
            # USt. einmal am Ende anwendet. In exakter Arithmetik ist das
            # dasselbe, in gerundeter nicht – bei einem Bruttopreis mit vier
            # Nachkommastellen (die API rundet auf vier, siehe `api.py`) gingen
            # die beiden Wege in rund jedem sechsten Fall um 0,0001 ct/kWh
            # auseinander. Das Wiki sagt zu, dass dieses Attribut dem Sensorwert
            # entspricht; über `all_in_value` gilt das per Konstruktion.
            "total_eur_kwh": to_eur(data.all_in_value(price)) if price else None,
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
            # Unterscheidet "noch nicht veröffentlicht" von "leer": Beides
            # ergibt sonst dieselbe leere Liste. Anders als die Liste selbst
            # wird dieser Wert vom Recorder mitgeschrieben, taugt also auch
            # zur Frage "ab wann waren die Preise da".
            "prices_tomorrow_valid": data.has_prices_for(tomorrow),
        }

    def _rank_attributes(self) -> dict | None:
        """Einordnung des laufenden Intervalls, für beide Kennzahl-Sensoren.

        Beide tragen dieselben Attribute, damit jeder für sich verständlich ist:
        Wer nur das Quantil im Dashboard hat, sieht den Rang trotzdem, und
        umgekehrt. ``None``, solange kein Intervall läuft – ein Wörterbuch
        voller ``None`` sähe aus wie eine Aussage, ist aber keine.
        """
        einordnung = self.coordinator.data.price_rank()
        if einordnung is None:
            return None

        return {
            "rank": einordnung.rank,
            # Nenner der Einordnung: 96 an einem vollständigen Viertelstundentag.
            "interval_count": einordnung.count,
            "cheaper_intervals": einordnung.cheaper,
            # Das eigene Intervall eingeschlossen, also mindestens 1.
            "equal_intervals": einordnung.equal,
            "quantile_percent": einordnung.quantile,
            # Gleichstandsregel am Objekt dokumentiert: Ein Gleichstand wird
            # hälftig geteilt (Mittelrang), nicht einer Seite zugeschlagen.
            "quantile_method": "midrank",
            # Bezugsgröße ist der Gesamtpreis, nicht der reine Arbeitspreis.
            "reference": "total_price",
        }
