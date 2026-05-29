"""DataUpdateCoordinator für die smartTIMES Integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MarketPrice, SmartTimesApiClient, SmartTimesApiError, SmartTimesResult
from .api import FeeEntry
from .const import (
    DOMAIN,
    MIN_FETCH_INTERVAL_MINUTES,
    RECALC_INTERVAL_MINUTES,
    STATUS_OFF_PEAK,
    STATUS_PEAK,
    STATUS_SHOULDER,
    VAT_RATE,
)
from .grid_fees import GridZone
from .surcharges import (
    surcharge_breakdown as tax_breakdown,
    total_surcharge_ct_per_kwh as total_tax_ct_per_kwh,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SmartTimesData:
    """Aufbereitete Daten, die der Koordinator den Entitäten bereitstellt."""

    tariff: str
    unit: str
    interval_minutes: int
    include_vat: bool
    prices: list[MarketPrice] = field(default_factory=list)
    basic_fees: list[FeeEntry] = field(default_factory=list)
    basic_fee_unit: str | None = None
    grid_zone: GridZone | None = None

    def current(self, moment: datetime | None = None) -> MarketPrice | None:
        """Der für ``moment`` (Standard: jetzt) gültige Preis-Eintrag."""
        moment = moment or dt_util.now()
        for price in self.prices:
            if price.start <= moment < price.end:
                return price
        return None

    def for_day(self, day) -> list[MarketPrice]:
        """Alle Preis-Einträge eines bestimmten lokalen Kalendertages."""
        return [
            price
            for price in self.prices
            if dt_util.as_local(price.start).date() == day
        ]

    def upcoming(self, moment: datetime | None = None) -> list[MarketPrice]:
        """Alle Preis-Einträge ab ``moment`` (Standard: jetzt)."""
        moment = moment or dt_util.now()
        return [price for price in self.prices if price.end > moment]

    def value(self, price: MarketPrice) -> float:
        """Arbeitspreis eines Eintrags gemäß Brutto-/Netto-Einstellung."""
        return price.price(self.include_vat)

    def _apply_vat(self, net_value: float) -> float:
        """Wendet die USt. gemäß Brutto-/Netto-Einstellung auf einen Nettowert an."""
        if self.include_vat:
            return net_value * (1.0 + VAT_RATE)
        return net_value

    def _grid_fee_net(self, moment: datetime) -> float:
        """Netto-Netzentgelt (ct/kWh) zu ``moment`` (0, wenn kein Netzgebiet)."""
        if self.grid_zone is None:
            return 0.0
        return self.grid_zone.total_ct_per_kwh(moment)

    def _surcharges_net(self, moment: datetime) -> float:
        """Summe aller Nebenkosten (Abgaben + Netzentgelte) netto in ct/kWh."""
        day = dt_util.as_local(moment).date()
        return total_tax_ct_per_kwh(day) + self._grid_fee_net(moment)

    def all_in_value(self, price: MarketPrice) -> float:
        """Gesamtpreis (Arbeitspreis + Nebenkosten) in ct/kWh.

        Die Nebenkosten gelten je nach Zeitpunkt des Intervalls (Abgaben nach
        Kalendertag, Netzentgelte zusätzlich nach SNAP-Fenster). Die USt. wird
        – wie in Österreich üblich – auf die *Summe* aus Arbeitspreis und
        Abgaben/Netzentgelten erhoben, daher wird hier netto summiert und die
        Steuer einmal am Ende angewendet.
        """
        net = price.net_ct_per_kwh + self._surcharges_net(price.start)
        return round(self._apply_vat(net), 4)

    def surcharge_breakdown(self, moment: datetime | None = None) -> dict[str, float]:
        """Nebenkosten je Position in ct/kWh (gemäß Brutto-/Netto-Einstellung)."""
        moment = moment or dt_util.now()
        day = dt_util.as_local(moment).date()
        items = dict(tax_breakdown(day))
        if self.grid_zone is not None:
            items.update(self.grid_zone.breakdown(moment))
        return {key: round(self._apply_vat(net), 4) for key, net in items.items()}

    def surcharges_total(self, moment: datetime | None = None) -> float:
        """Summe aller Nebenkosten in ct/kWh (gemäß Brutto-/Netto-Einstellung)."""
        moment = moment or dt_util.now()
        return round(self._apply_vat(self._surcharges_net(moment)), 4)

    def basic_fee(self, moment: datetime | None = None) -> float | None:
        """Die für ``moment`` gültige Grundgebühr (gemäß Brutto-/Netto-Einstellung)."""
        if not self.basic_fees:
            return None
        moment = moment or dt_util.now()
        applicable = [f for f in self.basic_fees if f.start <= moment]
        entry = applicable[-1] if applicable else self.basic_fees[0]
        return entry.value(self.include_vat)

    def price_levels(self) -> list[float]:
        """Sortierte, eindeutige Brutto-Preisstufen über alle vorliegenden Daten.

        smartTIMES teilt den Tag in feste Preisstufen (Tarifzonen) ein – über
        die vorliegenden Tage ergeben sich daraus die gültigen Stufen.
        """
        return sorted({round(p.gross_ct_per_kwh, 3) for p in self.prices})

    def classify(self, gross_value: float) -> str | None:
        """Ordnet einen Bruttopreis einer Tarifzone zu."""
        levels = self.price_levels()
        if not levels:
            return None
        eps = 1e-6
        if gross_value <= levels[0] + eps:
            return STATUS_OFF_PEAK
        if gross_value >= levels[-1] - eps:
            return STATUS_PEAK
        return STATUS_SHOULDER

    def status(self, moment: datetime | None = None) -> str | None:
        """Die aktuell gültige Tarifzone (Off-Peak/Shoulder/Peak)."""
        price = self.current(moment)
        if price is None:
            return None
        return self.classify(price.gross_ct_per_kwh)

    def _display(self, gross_value: float) -> float:
        """Bruttopreis gemäß Brutto-/Netto-Einstellung umrechnen."""
        if self.include_vat:
            return round(gross_value, 4)
        return round(gross_value / (1.0 + VAT_RATE), 4)

    def level_prices(self) -> dict[str, float]:
        """Zuordnung Tarifzone -> Preis (gemäß Brutto-/Netto-Einstellung)."""
        levels = self.price_levels()
        if not levels:
            return {}
        result = {
            STATUS_OFF_PEAK: self._display(levels[0]),
            STATUS_PEAK: self._display(levels[-1]),
        }
        if len(levels) >= 3:
            result[STATUS_SHOULDER] = self._display(levels[len(levels) // 2])
        return result

    def next_status_change(
        self, moment: datetime | None = None
    ) -> tuple[str | None, datetime | None]:
        """Nächste abweichende Tarifzone und deren Startzeitpunkt."""
        moment = moment or dt_util.now()
        current = self.status(moment)
        for price in self.prices:
            if price.start <= moment:
                continue
            status = self.classify(price.gross_ct_per_kwh)
            if status != current:
                return status, price.start
        return None, None


class SmartTimesCoordinator(DataUpdateCoordinator[SmartTimesData]):
    """Koordiniert das Laden der smartTIMES-Preise.

    Die Entitäten werden minütlich aktualisiert (damit der aktuelle Preis
    beim Wechsel der 15-Minuten-Zone sofort stimmt), die API selbst wird
    jedoch nur alle ``MIN_FETCH_INTERVAL_MINUTES`` aufgerufen – oder sofort,
    wenn die vorhandenen Daten den aktuellen Zeitpunkt nicht abdecken.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SmartTimesApiClient,
        include_vat: bool,
        grid_zone: GridZone | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(minutes=RECALC_INTERVAL_MINUTES),
        )
        self._client = client
        self._include_vat = include_vat
        self._grid_zone = grid_zone
        self._last_fetch: datetime | None = None
        self._last_result: SmartTimesResult | None = None

    @property
    def include_vat(self) -> bool:
        """Ob die Preise inkl. USt. (brutto) ausgewiesen werden."""
        return self._include_vat

    def _needs_fetch(self, now: datetime) -> bool:
        """Entscheidet, ob ein neuer API-Aufruf nötig ist."""
        if self._last_result is None or self._last_fetch is None:
            return True
        if now - self._last_fetch >= timedelta(minutes=MIN_FETCH_INTERVAL_MINUTES):
            return True
        # Decken die vorhandenen Daten den aktuellen Zeitpunkt nicht mehr ab,
        # brauchen wir sofort frische Preise (z. B. nach Mitternacht).
        if not self._last_result.prices or self._last_result.prices[-1].end <= now:
            return True
        return False

    async def _async_update_data(self) -> SmartTimesData:
        now = dt_util.now()

        if self._needs_fetch(now):
            try:
                self._last_result = await self._client.async_get_prices()
                self._last_fetch = now
            except SmartTimesApiError as err:
                if self._last_result is None:
                    raise UpdateFailed(str(err)) from err
                # Frühere Daten behalten, falls ein einzelner Abruf scheitert.
                _LOGGER.warning(
                    "Aktualisierung der smartTIMES-Preise fehlgeschlagen, "
                    "verwende zwischengespeicherte Daten: %s",
                    err,
                )

        result = self._last_result
        assert result is not None  # nach erfolgreichem ersten Abruf garantiert
        return SmartTimesData(
            tariff=result.tariff,
            unit=result.unit,
            interval_minutes=result.interval_minutes,
            include_vat=self._include_vat,
            prices=result.prices,
            basic_fees=result.basic_fees,
            basic_fee_unit=result.basic_fee_unit,
            grid_zone=self._grid_zone,
        )
