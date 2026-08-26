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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from . import SmartTimesConfigEntry
from .const import (
    JITTER_SPAN_SECONDS,
    SUBENTRY_TYPE_CHEAP_HOUR,
    UNIT_EUR_PER_KWH,
    to_eur,
)
from .coordinator import SmartTimesCoordinator
from .entity import CheapHourEntity

# Reine Koordinator-Lesesensoren ohne eigene API-Aufrufe oder Aktionen – eine
# Drosselung paralleler Updates ist daher nicht nötig.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartTimesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
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


class CheapHourBinarySensor(CheapHourEntity, BinarySensorEntity):
    """`on`, wenn die laufende Viertelstunde zu den günstigsten des Tages zählt."""

    _attr_translation_key = "cheap_hour"
    # Günstig-Intervalle und Schaltfenster sind minütlich neu berechnete, rein
    # zukunftsgerichtete Listen - Recorder-History bringt hier keinen Mehrwert.
    # Ohne den Ausschluss schreibt jeder Untereintrags-Sensor sie bei jedem
    # Attributwechsel mit in die Datenbank, und current_price_eur_kwh wechselt
    # mit jedem Preisintervall (bei smartCONTROL viertelstündlich).
    _unrecorded_attributes = frozenset({"cheap_intervals", "cheap_windows"})

    def __init__(
        self,
        coordinator: SmartTimesCoordinator,
        subentry: ConfigSubentry,
        hub_id: str | None = None,
    ) -> None:
        """Initialisiert den Sensor aus dem Untereintrag (Stundenzahl, Logik, Jitter)."""
        super().__init__(coordinator, subentry, hub_id)
        self._attr_unique_id = f"{subentry.subentry_id}_cheap_hour"

    @property
    def is_on(self) -> bool | None:
        """Ob der aktuelle Zeitpunkt im (gejitterten) günstigen Fenster liegt."""
        data = self.coordinator.data
        now = dt_util.now()
        # Ohne Preisabdeckung für „jetzt" ist der Zustand unbekannt.
        if data.current(now) is None:
            return None
        return data.is_cheap_now(
            now,
            self._cheap_hours,
            self._jitter_phase,
            self._cheap_mode,
            self._exact_hours,
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Schwellwert, günstige Intervalle, gejitterte Fenster und nächster Start."""
        data = self.coordinator.data
        now = dt_util.now()
        today = now.date()
        price = data.current(now)
        cheap = data.cheap_intervals(
            today, self._cheap_hours, self._cheap_mode, self._exact_hours
        )
        windows = data.jittered_cheap_windows(
            today,
            self._cheap_hours,
            self._jitter_phase,
            self._cheap_mode,
            self._exact_hours,
        )
        next_on = data.next_cheap_on(
            now,
            self._cheap_hours,
            self._jitter_phase,
            self._cheap_mode,
            self._exact_hours,
        )

        def current_price() -> StateType:
            return to_eur(data.all_in_value(price)) if price else None

        return {
            "cheap_hours": self._cheap_hours,
            "cheap_mode": self._cheap_mode,
            # Ob die Stundenzahl exakt gilt, statt bei Preisgleichstand darüber
            # hinaus zu erweitern (nur im Einzelstunden-Modus wirksam).
            "exact_hours": self._exact_hours,
            "threshold_eur_kwh": to_eur(
                data.cheap_cutoff(
                    today, self._cheap_hours, self._cheap_mode, self._exact_hours
                )
            ),
            "current_price_eur_kwh": current_price(),
            "unit": UNIT_EUR_PER_KWH,
            "vat_included": data.include_vat,
            # Last-Glättung: konstanter Einschalt-Versatz dieses Sensors in
            # Sekunden (deterministisch, vom Nutzer nicht änderbar).
            "jitter_offset_seconds": round(
                self._jitter_phase * JITTER_SPAN_SECONDS
            ),
            "next_cheap_start": next_on.isoformat() if next_on else None,
            "cheap_intervals": [
                {
                    "start": p.start.isoformat(),
                    "end": p.end.isoformat(),
                    "price": to_eur(data.all_in_value(p)),
                }
                for p in cheap
            ],
            # Tatsächliche, gejitterte Schaltfenster (so, wie der Sensor schaltet).
            # ``exceeds_cheap_hours``: Der Block reicht wegen eines
            # Preis-Gleichstands über die eingestellte Stundenzahl hinaus – rein
            # informativ, das Schaltverhalten ist dasselbe.
            "cheap_windows": [
                {
                    "on": on_time.isoformat(),
                    "off": off_time.isoformat(),
                    "exceeds_cheap_hours": exceeds,
                }
                for on_time, off_time, exceeds in windows
            ],
        }
