"""Client für die smartENERGY smartTIMES Preis-API."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp
from homeassistant.util import dt as dt_util

from .const import API_TIMEOUT, API_URL, VAT_RATE

_LOGGER = logging.getLogger(__name__)


class SmartTimesApiError(Exception):
    """Wird ausgelöst, wenn die API nicht erreichbar ist oder ungültige Daten liefert."""


@dataclass(slots=True)
class MarketPrice:
    """Ein Preis-Eintrag für ein Zeitintervall.

    Der Preis wird brutto (inkl. USt.) in ct/kWh gespeichert – genau so,
    wie ihn die API liefert. Die Netto-Variante wird bei Bedarf berechnet.
    """

    start: datetime
    end: datetime
    gross_ct_per_kwh: float

    @property
    def net_ct_per_kwh(self) -> float:
        """Nettopreis (ohne 20 % USt.) in ct/kWh."""
        return round(self.gross_ct_per_kwh / (1.0 + VAT_RATE), 4)

    def price(self, include_vat: bool) -> float:
        """Preis je nach gewählter Brutto-/Netto-Einstellung."""
        return self.gross_ct_per_kwh if include_vat else self.net_ct_per_kwh


@dataclass(slots=True)
class SmartTimesResult:
    """Ergebnis eines API-Abrufs."""

    tariff: str
    interval_minutes: int
    unit: str
    prices: list[MarketPrice]


class SmartTimesApiClient:
    """Kapselt die HTTP-Aufrufe an die smartTIMES-API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def async_get_prices(self) -> SmartTimesResult:
        """Lädt die aktuellen Tarifpreise von der API."""
        try:
            async with asyncio.timeout(API_TIMEOUT):
                response = await self._session.get(
                    API_URL,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = await response.json()
        except asyncio.TimeoutError as err:
            raise SmartTimesApiError(
                "Zeitüberschreitung beim Abruf der smartTIMES-API"
            ) from err
        except aiohttp.ClientError as err:
            raise SmartTimesApiError(
                f"Fehler beim Abruf der smartTIMES-API: {err}"
            ) from err

        return self._parse(payload)

    @staticmethod
    def _parse(payload: dict) -> SmartTimesResult:
        """Wertet die JSON-Antwort der API aus."""
        if not isinstance(payload, dict):
            raise SmartTimesApiError("Unerwartetes Antwortformat der API")

        tariff = payload.get("tariff", "smartTIMES")
        unit = payload.get("unit", "ct/kWh")
        try:
            interval_minutes = int(payload.get("interval", 15))
        except (TypeError, ValueError):
            interval_minutes = 15

        raw_data = payload.get("data")
        if not isinstance(raw_data, list) or not raw_data:
            raise SmartTimesApiError("Die API hat keine Preisdaten geliefert")

        delta = timedelta(minutes=interval_minutes)
        prices: list[MarketPrice] = []
        for entry in raw_data:
            try:
                start = SmartTimesApiClient._parse_date(entry["date"])
                value = float(entry["value"])
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.debug("Überspringe ungültigen Preis-Eintrag %s: %s", entry, err)
                continue
            prices.append(
                MarketPrice(
                    start=start,
                    end=start + delta,
                    gross_ct_per_kwh=round(value, 4),
                )
            )

        if not prices:
            raise SmartTimesApiError("Keine gültigen Preisdaten in der API-Antwort")

        prices.sort(key=lambda p: p.start)
        return SmartTimesResult(
            tariff=tariff,
            interval_minutes=interval_minutes,
            unit=unit,
            prices=prices,
        )

    @staticmethod
    def _parse_date(value: str) -> datetime:
        """Wandelt das ``date``-Feld der API in ein zeitzonenbehaftetes datetime um.

        Laut Spezifikation handelt es sich um *lokale* Datum/Uhrzeit. Liefert die
        API keinen Zeitzonen-Offset, wird die in Home Assistant konfigurierte
        Zeitzone angenommen (für österreichische Nutzer Europe/Vienna).
        """
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return parsed
