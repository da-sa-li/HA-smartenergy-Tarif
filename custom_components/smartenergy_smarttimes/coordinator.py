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
from .const import (
    DOMAIN,
    MIN_FETCH_INTERVAL_MINUTES,
    RECALC_INTERVAL_MINUTES,
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
        """Preis eines Eintrags gemäß Brutto-/Netto-Einstellung."""
        return price.price(self.include_vat)


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
        )
