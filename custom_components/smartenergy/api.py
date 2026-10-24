"""Client für die smartENERGY Preis-API (smartTIMES und smartCONTROL).

Der dritte Tarif, smartNIGHT, hat keinen eigenen Endpunkt: Er wird aus der
smartTIMES-Antwort berechnet und sitzt deshalb in ``smartnight.py`` auf diesem
Client auf.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Final
from zoneinfo import ZoneInfo

import aiohttp
from homeassistant.util import dt as dt_util

from .const import (
    API_TIMEOUT,
    API_URL,
    UNIT_CT_PER_KWH,
    USER_AGENT_PRODUCT,
    VAT_RATE,
)

_LOGGER = logging.getLogger(__name__)

# Zeitzone, in der die API ihre Wanduhrzeiten schreibt. Gebraucht wird sie nur,
# um die doppelte Stunde der Herbstumstellung zuzuordnen (siehe
# `SmartTimesApiClient._ordne_doppelte_stunde_zu`); sonst gilt der Offset der
# Antwort.
_API_TIME_ZONE: Final = ZoneInfo("Europe/Vienna")


def _build_user_agent(
    integration_version: str | None, documentation_url: str | None
) -> str:
    """Baut den User-Agent-String nach dem Schema ``Produkt/Version (+URL)``.

    Tarifneutral: derselbe Client bedient alle Tarife der Integration. Manche
    APIs lehnen Anfragen ohne "echten" UA mit 403 ab – daher setzen wir einen,
    der zusätzlich die Integrationsversion und einen Doku-Link trägt, damit
    smartENERGY bei Rückfragen eine Anlaufstelle hat.
    """
    product = USER_AGENT_PRODUCT
    if integration_version:
        product = f"{product}/{integration_version}"
    if documentation_url:
        return f"{product} (+{documentation_url})"
    return product


# 4xx-Status, bei denen ein baldiger neuer Versuch trotzdem sinnvoll ist: 408
# (serverseitige Zeitüberschreitung) und 429 (Rate-Limit, üblicherweise zusammen
# mit einem Retry-After-Header). Alle übrigen 4xx gelten als dauerhaft.
_RETRYABLE_CLIENT_ERRORS: Final[frozenset[int]] = frozenset({408, 429})


def _is_permanent_status(status: int) -> bool:
    """Ob ein HTTP-Status als dauerhafte Ablehnung zu werten ist."""
    return 400 <= status < 500 and status not in _RETRYABLE_CLIENT_ERRORS


def _parse_retry_after(value: str | None) -> timedelta | None:
    """Wertet den ``Retry-After``-Header aus (RFC 9110).

    Zulässig sind eine Anzahl Sekunden oder ein HTTP-Datum; ein bereits
    verstrichenes Datum ergibt ``timedelta(0)``. Fehlt der Header oder ist er
    unbrauchbar, wird ``None`` zurückgegeben – dann gilt allein die eigene
    Wartezeit des Koordinators.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return timedelta(seconds=max(0, int(value)))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        # HTTP-Daten sind laut RFC 9110 stets in GMT angegeben.
        moment = moment.replace(tzinfo=UTC)
    return max(timedelta(0), moment - dt_util.utcnow())


class SmartTimesApiError(Exception):
    """Wird ausgelöst, wenn die API nicht erreichbar ist oder ungültige Daten liefert."""

    def __init__(self, message: str, retry_after: timedelta | None = None) -> None:
        """Initialisiert den Fehler mit der optional vom Server gewünschten Wartezeit."""
        super().__init__(message)
        self.retry_after = retry_after


class SmartTimesApiPermanentError(SmartTimesApiError):
    """Die API lehnt die Anfrage dauerhaft ab (4xx außer 408/429).

    Anders als bei einer Zeitüberschreitung oder einem Serverfehler hilft rasches
    Wiederholen hier nicht: Der Endpunkt ist verschwunden (404/410) oder der
    Zugriff wird verweigert (401/403). Der Koordinator wartet daraufhin das
    Maximal-Intervall ab, gibt aber nicht endgültig auf – so erholt sich die
    Integration selbst wieder, falls die Ablehnung doch nur vorübergehend war.
    """


class SmartTimesApiTimeoutError(SmartTimesApiError):
    """Der Abruf der API hat das Zeitlimit überschritten.

    Eigene, vom generischen ``SmartTimesApiError`` unterscheidbare Fehlerart,
    damit der Options-/Einrichtungs-Flow gezielter Auskunft geben kann. Am
    Retry-Verhalten des Koordinators ändert das nichts – dort zählt weiterhin
    nur die Unterscheidung dauerhaft/vorübergehend (``SmartTimesApiPermanentError``).
    """


class SmartTimesApiPayloadError(SmartTimesApiError):
    """Die Antwort der API lässt sich nicht auswerten (kein JSON, unerwartetes
    Format oder keine gültigen Preisdaten).

    Eigene Fehlerart, damit der Config-Flow gezielt auf eine mögliche
    Formatänderung der smartENERGY-API hinweisen kann.
    """


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
class FeeEntry:
    """Ein zeitlich gültiger Grundgebühr-Eintrag (brutto)."""

    start: datetime
    gross_value: float

    def value(self, include_vat: bool) -> float:
        """Grundgebühr je nach Brutto-/Netto-Einstellung."""
        if include_vat:
            return self.gross_value
        return round(self.gross_value / (1.0 + VAT_RATE), 4)


@dataclass(slots=True)
class SmartTimesResult:
    """Ergebnis eines API-Abrufs."""

    tariff: str
    interval_minutes: int
    unit: str
    prices: list[MarketPrice]
    basic_fees: list[FeeEntry] = field(default_factory=list)
    basic_fee_unit: str | None = None


class SmartTimesApiClient:
    """Kapselt die HTTP-Aufrufe an die smartENERGY-API (smartTIMES/smartCONTROL).

    smartNIGHT nutzt denselben Client über den ableitenden Untertyp in
    ``smartnight.py``.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_url: str = API_URL,
        integration_version: str | None = None,
        documentation_url: str | None = None,
    ) -> None:
        """Initialisiert den Client mit Session und Tarif-API-URL.

        ``api_url`` bestimmt den abzurufenden Tarif (smartTIMES- bzw.
        smartCONTROL-Endpunkt). Standard ist die smartTIMES-URL, damit
        bestehende Aufrufer ohne Anpassung weiterfunktionieren.
        ``integration_version``/``documentation_url`` fließen in den
        User-Agent ein (siehe ``_build_user_agent``); ohne Angabe wird ein
        Fallback-UA ohne Version/Link verwendet.
        """
        self._session = session
        self._api_url = api_url
        self._headers = {
            "Accept": "application/json",
            "User-Agent": _build_user_agent(integration_version, documentation_url),
        }

    async def async_get_prices(self) -> SmartTimesResult:
        """Lädt die aktuellen Tarifpreise von der konfigurierten API."""
        try:
            async with asyncio.timeout(API_TIMEOUT):
                response = await self._session.get(
                    self._api_url,
                    headers=self._headers,
                )
                text = await response.text()
                response.raise_for_status()
        except TimeoutError as err:
            raise SmartTimesApiTimeoutError(
                f"Zeitüberschreitung beim Abruf der smartENERGY-API ({self._api_url})"
            ) from err
        except aiohttp.ClientResponseError as err:
            retry_after = _parse_retry_after(
                err.headers.get("Retry-After") if err.headers is not None else None
            )
            message = (
                f"smartENERGY-API antwortete mit HTTP {err.status} ({err.message})"
            )
            if _is_permanent_status(err.status):
                raise SmartTimesApiPermanentError(message, retry_after) from err
            raise SmartTimesApiError(message, retry_after) from err
        except aiohttp.ClientError as err:
            raise SmartTimesApiError(
                f"Netzwerkfehler beim Abruf der smartENERGY-API: {err}"
            ) from err

        try:
            payload = json.loads(text)
        except ValueError as err:
            snippet = text[:200].replace("\n", " ")
            raise SmartTimesApiPayloadError(
                f"Ungültige (kein JSON) Antwort der smartENERGY-API. Auszug: {snippet!r}"
            ) from err

        return self._parse(payload)

    @staticmethod
    def _parse(payload: dict) -> SmartTimesResult:
        """Wertet die JSON-Antwort der API aus.

        Die smartTIMES-API liefert die Energiepreise verschachtelt unter
        ``energyPrice`` mit Einträgen ``values`` / ``dateTimeFrom``. Das flache
        Format (``data`` / ``date`` auf oberster Ebene) – wie es auch der
        smartCONTROL-Markt-Endpunkt liefert – wird als Fallback unterstützt.
        ``_parse_date`` respektiert dabei einen vorhandenen Zeitzonen-Offset;
        nur die doppelte Stunde der Herbstumstellung ordnet
        ``_ordne_doppelte_stunde_zu`` nach der Reihenfolge der Einträge zu.
        """
        if not isinstance(payload, dict):
            raise SmartTimesApiPayloadError("Unerwartetes Antwortformat der API")

        # Energiepreis-Block bestimmen (neues Format) bzw. auf oberste Ebene
        # zurückfallen (dokumentiertes Format).
        energy = payload.get("energyPrice")
        if not isinstance(energy, dict):
            energy = payload

        tariff = payload.get("tariff") or energy.get("tariff") or "smartTIMES"
        unit = energy.get("unit", UNIT_CT_PER_KWH)
        try:
            interval_minutes = int(energy.get("interval", 15))
        except (TypeError, ValueError):
            interval_minutes = 15

        raw_values = energy.get("values")
        if not isinstance(raw_values, list):
            raw_values = energy.get("data")
        if not isinstance(raw_values, list) or not raw_values:
            raise SmartTimesApiPayloadError(
                "Die API hat keine Preisdaten geliefert. Vorhandene Felder: "
                f"oberste Ebene={sorted(payload)}, energyPrice={sorted(energy)}"
            )

        delta = timedelta(minutes=interval_minutes)
        entries = [
            parsed
            for parsed in map(SmartTimesApiClient._parse_entry, raw_values)
            if parsed is not None
        ]
        starts = SmartTimesApiClient._ordne_doppelte_stunde_zu(
            [start for start, _ in entries]
        )
        prices = [
            MarketPrice(
                start=start,
                end=start + delta,
                gross_ct_per_kwh=round(value, 4),
            )
            for start, (_, value) in zip(starts, entries, strict=True)
        ]

        if not prices:
            raise SmartTimesApiPayloadError("Keine gültigen Preisdaten in der API-Antwort")

        prices.sort(key=lambda p: p.start)

        basic_fees, basic_fee_unit = SmartTimesApiClient._parse_basic_fee(payload)

        return SmartTimesResult(
            tariff=tariff,
            interval_minutes=interval_minutes,
            unit=unit,
            prices=prices,
            basic_fees=basic_fees,
            basic_fee_unit=basic_fee_unit,
        )

    @staticmethod
    def _ordne_doppelte_stunde_zu(starts: list[datetime]) -> list[datetime]:
        """Ordnet die doppelt durchlaufene Stunde der Herbstumstellung zu.

        Am letzten Oktobersonntag läuft die Uhr von 02:00 bis 02:59 zweimal. Die
        API schreibt beide Durchläufe als Wanduhrzeit und – Stand Oktober 2026 –
        beide mit dem Winterzeit-Offset ``+01:00`` (Issue #126). Übernommen hätte
        die erste Stunde Sommerzeit damit keinen Preis, die erste Stunde
        Winterzeit dagegen zwei. Ohne Offset wären die Durchläufe gar nicht zu
        unterscheiden (Issue #75).

        Kommt eine solche mehrdeutige Wanduhrzeit mehrfach vor, entscheidet
        deshalb die **Reihenfolge der Antwort**: Das erste Vorkommen ist
        Sommerzeit, das zweite Winterzeit. Ein Offset, der dazu passt, bleibt
        so unverändert; die Korrektur ändert nur, was ohnehin nicht stimmt.
        Einzeln vorkommende Zeiten und Zeitstempel, deren Offset nicht zu
        Europe/Vienna gehört, bleiben, wie sie sind.

        Alle Zeitpunkte tragen danach einen **festen Offset** statt einer Zone,
        auch die ohne Offset gelieferten. Zwei Zeitpunkte derselben ``ZoneInfo``
        vergleicht Python nach Wanduhrzeit und übergeht ``fold``; mit einem
        Zeitpunkt einer anderen Zone ist ein mehrdeutiger nie gleich (PEP 495).
        Beides bräche an der doppelten Stunde den Abgleich „Ende = nächster
        Beginn“. Für Antworten mit Offset, den Normalfall, ändert das nichts.
        """

        def mehrdeutig(start: datetime) -> bool:
            wand = start.replace(tzinfo=None)
            moeglich = set()
            for fold in (0, 1):
                lokal = wand.replace(tzinfo=_API_TIME_ZONE, fold=fold)
                # Wanduhrzeiten der Frühjahrslücke gibt es nicht: Sie kämen
                # verschoben zurück und sind hier nicht gemeint.
                zurueck = lokal.astimezone(UTC).astimezone(_API_TIME_ZONE)
                if zurueck.replace(tzinfo=None) == wand:
                    moeglich.add(lokal.utcoffset())
            return len(moeglich) == 2 and start.utcoffset() in moeglich

        walls = [start.replace(tzinfo=None) for start in starts]
        haeufigkeit = Counter(
            wand for start, wand in zip(starts, walls, strict=True) if mehrdeutig(start)
        )
        gesehen: set[datetime] = set()
        result: list[datetime] = []
        for start, wand in zip(starts, walls, strict=True):
            offset = start.utcoffset()
            if haeufigkeit[wand] >= 2:
                fold = 1 if wand in gesehen else 0
                gesehen.add(wand)
                offset = wand.replace(tzinfo=_API_TIME_ZONE, fold=fold).utcoffset()
                if offset != start.utcoffset():
                    _LOGGER.debug(
                        "Doppelte Stunde der Zeitumstellung zugeordnet: %s -> %s",
                        start.isoformat(),
                        offset,
                    )
            result.append(wand.replace(tzinfo=timezone(offset)))
        return result

    @staticmethod
    def _parse_basic_fee(payload: dict) -> tuple[list[FeeEntry], str | None]:
        """Liest den optionalen Grundgebühr-Block (``basicFee``) aus."""
        basic = payload.get("basicFee")
        if not isinstance(basic, dict):
            return [], None

        unit = basic.get("unit")
        raw_values = basic.get("values")
        if not isinstance(raw_values, list):
            return [], unit

        fees: list[FeeEntry] = []
        for entry in raw_values:
            parsed = SmartTimesApiClient._parse_entry(entry)
            if parsed is None:
                continue
            start, value = parsed
            fees.append(FeeEntry(start=start, gross_value=round(value, 4)))

        fees.sort(key=lambda f: f.start)
        return fees, unit

    @staticmethod
    def _parse_entry(entry: object) -> tuple[datetime, float] | None:
        """Liest einen einzelnen ``{date(TimeFrom), value}``-Eintrag aus."""
        if not isinstance(entry, dict):
            return None
        raw_date = entry.get("dateTimeFrom") or entry.get("date")
        raw_value = entry.get("value")
        if raw_date is None or raw_value is None:
            return None
        try:
            return SmartTimesApiClient._parse_date(raw_date), float(raw_value)
        except (TypeError, ValueError) as err:
            _LOGGER.debug("Überspringe ungültigen Eintrag %s: %s", entry, err)
            return None

    @staticmethod
    def _parse_date(value: str) -> datetime:
        """Wandelt ein Datums-Feld der API in ein zeitzonenbehaftetes datetime um.

        Laut Spezifikation handelt es sich um *lokale* Datum/Uhrzeit. Liefert die
        API keinen Zeitzonen-Offset, wird die in Home Assistant konfigurierte
        Zeitzone angenommen (für österreichische Nutzer Europe/Vienna).
        """
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return parsed
