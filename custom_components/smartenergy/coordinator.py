"""DataUpdateCoordinator für die smartTIMES Integration."""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MarketPrice, SmartTimesApiClient, SmartTimesApiError, SmartTimesResult
from .api import FeeEntry
from .const import (
    CHEAP_MODE_CONSECUTIVE,
    DEFAULT_CHEAP_MODE,
    DOMAIN,
    FETCH_JITTER_MINUTES,
    FETCH_RETRY_INTERVAL_MINUTES,
    NEXT_DAY_PRICES_HOUR,
    RECALC_INTERVAL_MINUTES,
    VAT_RATE,
)
from .grid_fees import GridZone
from .jitter import jittered_window
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
    # Abwicklungsgebühr (netto, ct/kWh). Nur bei smartCONTROL > 0; sie wird wie
    # die übrigen Nebenkosten netto summiert (USt. einmal am Ende).
    handling_fee_net: float = 0.0

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
        """Summe aller Nebenkosten netto in ct/kWh.

        Enthält Abgaben, Netzentgelte und – bei smartCONTROL – die
        Abwicklungsgebühr. Die USt. wird erst am Ende auf die Summe angewendet.
        """
        day = dt_util.as_local(moment).date()
        return (
            total_tax_ct_per_kwh(day)
            + self._grid_fee_net(moment)
            + self.handling_fee_net
        )

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
        # Abwicklungsgebühr nur ausweisen, wenn sie greift (smartCONTROL); bei
        # smartTIMES (0,0) bleibt die Aufschlüsselung unverändert.
        if self.handling_fee_net:
            items["handling_fee"] = self.handling_fee_net
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

    def _cheap_count(self, cheap_hours: float) -> int:
        """Anzahl der als günstig zu markierenden Intervalle pro Tag."""
        if self.interval_minutes <= 0:
            return 1
        per_hour = 60 / self.interval_minutes
        # Aufrunden, damit bei krummen Werten (z. B. 1,25 h bei 30-Minuten-
        # Intervallen) die zugesagte „mindestens so viele Intervalle"-Semantik
        # eingehalten wird, statt zu wenige Intervalle zu markieren.
        return max(1, math.ceil(cheap_hours * per_hour))

    def _cheap_selection(
        self, day, cheap_hours: float, mode: str = DEFAULT_CHEAP_MODE
    ) -> tuple[set[datetime], set[datetime]]:
        """``(alle, strikte)`` Startzeiten der günstigsten Intervalle eines Tages.

        ``mode`` steuert die Auswahllogik:

        * ``CHEAP_MODE_INDIVIDUAL`` (Standard): die günstigsten **Einzel**-
          Intervalle des Tages – sie dürfen über den Tag verteilt (zerteilt)
          sein. ``strikte`` enthält **genau** so viele Intervalle, wie
          ``cheap_hours`` ergibt (Gleichstand nach Startzeit aufgelöst).
          ``alle`` enthält zusätzlich die bei Gleichstand am Schwellwert
          mitmarkierten „Überschuss"-Intervalle: Teilen sich mehrere Intervalle
          den Preis des teuersten noch gewählten Intervalls, werden *alle*
          davon markiert – auch wenn dadurch mehr als ``cheap_hours`` zustande
          kommen. So bleibt keine gleich günstige Stunde unberücksichtigt.
        * ``CHEAP_MODE_CONSECUTIVE``: ein einziger **zusammenhängender** Block
          „am Stück" – das günstigste lückenlose Zeitfenster aus ``cheap_hours``
          (siehe :meth:`_consecutive_selection`). Auch hier wird bei Gleichstand
          am Schwellwert verlängert: Grenzt direkt vor oder nach dem Block ein
          Intervall mit demselben Preis wie das teuerste Intervall des Blocks
          an, wird der Block zusammenhängend ausgedehnt. ``alle`` enthält diese
          Überschuss-Intervalle, ``strikte`` nur das ``cheap_hours``-Fenster.
        """
        prices = self.for_day(day)
        if not prices:
            return set(), set()
        count = min(self._cheap_count(cheap_hours), len(prices))
        if mode == CHEAP_MODE_CONSECUTIVE:
            return self._consecutive_selection(prices, count)
        return self._individual_selection(prices, count)

    def _individual_selection(
        self, prices: list[MarketPrice], count: int
    ) -> tuple[set[datetime], set[datetime]]:
        """``(alle, strikte)`` für die günstigsten **Einzel**-Intervalle.

        ``strikte`` sind die ``count`` günstigsten Intervalle (Gleichstand nach
        Startzeit aufgelöst); ``alle`` ergänzt die am Schwellwert gleich teuren
        „Überschuss"-Intervalle, sodass keine gleich günstige Stunde fehlt.
        """
        valued = [(self.all_in_value(p), p) for p in prices]
        ranked = sorted(valued, key=lambda item: (item[0], item[1].start))
        cutoff_value = ranked[count - 1][0]
        all_starts = {p.start for value, p in valued if value <= cutoff_value}
        strict_starts = {p.start for _, p in ranked[:count]}
        return all_starts, strict_starts

    def _consecutive_selection(
        self, prices: list[MarketPrice], count: int
    ) -> tuple[set[datetime], set[datetime]]:
        """``(alle, strikte)`` für den günstigsten **zusammenhängenden** Block.

        ``strikte`` ist das günstigste lückenlose Fenster aus ``count``
        aufeinanderfolgenden Intervallen (geringste Summe der Gesamtkosten,
        Gleichstand → frühestes Fenster). ``prices`` muss chronologisch sortiert
        sein (wie von :meth:`for_day` geliefert).

        ``alle`` verlängert diesen Block bei **Gleichstand**: Direkt
        angrenzende Intervalle (vor dem Beginn bzw. nach dem Ende), deren
        Gesamtpreis exakt dem teuersten Intervall des Blocks (dem Schwellwert)
        entspricht, werden mitmarkiert – analog zur Einzelstunden-Logik, aber
        zusammenhängend, sodass der Block „am Stück" bleibt.

        Sollten die Tagesdaten eine Lücke aufweisen und kein lückenloses Fenster
        der geforderten Länge existieren, wird auf die günstigsten
        Einzelintervalle ausgewichen, damit der Sensor nie dauerhaft „aus"
        bleibt.
        """
        n = len(prices)
        best_total: float | None = None
        best_index = 0
        for i in range(n - count + 1):
            window = prices[i : i + count]
            # Das Fenster muss zeitlich zusammenhängen (keine Lücke), sonst wäre
            # der Block nicht wirklich „am Stück".
            if any(
                window[j].end != window[j + 1].start for j in range(count - 1)
            ):
                continue
            total = sum(self.all_in_value(p) for p in window)
            if best_total is None or total < best_total - 1e-9:
                best_total = total
                best_index = i
        if best_total is None:
            return self._individual_selection(prices, count)

        lo = best_index
        hi = best_index + count  # exklusiver End-Index
        strict_starts = {prices[i].start for i in range(lo, hi)}
        cutoff = max(self.all_in_value(prices[i]) for i in range(lo, hi))
        # Bei Gleichstand zusammenhängend nach vorn/hinten ausdehnen – nur über
        # lückenlos angrenzende Intervalle, die den Schwellwert exakt treffen.
        while (
            lo - 1 >= 0
            and prices[lo - 1].end == prices[lo].start
            and abs(self.all_in_value(prices[lo - 1]) - cutoff) < 1e-9
        ):
            lo -= 1
        while (
            hi < n
            and prices[hi - 1].end == prices[hi].start
            and abs(self.all_in_value(prices[hi]) - cutoff) < 1e-9
        ):
            hi += 1
        all_starts = {prices[i].start for i in range(lo, hi)}
        return all_starts, strict_starts

    def _cheap_starts(
        self, day, cheap_hours: float, mode: str = DEFAULT_CHEAP_MODE
    ) -> set[datetime]:
        """Startzeiten *aller* günstigen Intervalle eines Tages (inkl. Gleichstand)."""
        return self._cheap_selection(day, cheap_hours, mode)[0]

    def cheap_intervals(
        self, day, cheap_hours: float, mode: str = DEFAULT_CHEAP_MODE
    ) -> list[MarketPrice]:
        """Die günstigsten Intervalle eines Tages (nach Gesamtkosten), chronologisch."""
        starts = self._cheap_starts(day, cheap_hours, mode)
        return [price for price in self.for_day(day) if price.start in starts]

    def cheap_cutoff(
        self, day, cheap_hours: float, mode: str = DEFAULT_CHEAP_MODE
    ) -> float | None:
        """Höchster Gesamtpreis (ct/kWh) unter den günstigen Intervallen des Tages."""
        intervals = self.cheap_intervals(day, cheap_hours, mode)
        if not intervals:
            return None
        return max(self.all_in_value(p) for p in intervals)

    def _cheap_blocks(
        self, day, cheap_hours: float, mode: str = DEFAULT_CHEAP_MODE
    ) -> list[tuple[datetime, datetime, bool]]:
        """Zusammenhängende Günstig-Blöcke eines Tages als ``(start, end, soft_end)``.

        Direkt aufeinanderfolgende günstige Intervalle werden zu einem Block
        zusammengefasst, damit der Jitter pro **Block** (nicht pro Intervall)
        wirkt – ein durchgehender günstiger Zeitraum wird so nie zerteilt. Im
        Modus ``CHEAP_MODE_CONSECUTIVE`` ist die Auswahl ohnehin bereits ein
        einziger zusammenhängender Block.

        ``soft_end`` ist ``True``, wenn das Blockende nur durch die
        Gleichstands-Mechanik zustande kommt: Das letzte Intervall des Blocks
        ist ein „Überschuss"-Intervall am Schwellwert, das über die
        konfigurierte Stundenzahl hinausgeht. Bei einem solchen Ende soll der
        Sensor nicht zusätzlich in die nächste (teurere) Preiszone ausgreifen.
        Das gilt für **beide** Modi: Auch ein zusammenhängender Block kann am
        Ende durch Gleichstand verlängert sein (siehe
        :meth:`_consecutive_selection`).
        """
        all_starts, strict_starts = self._cheap_selection(day, cheap_hours, mode)
        surplus = all_starts - strict_starts
        # [start, end, letzter Intervallstart]
        blocks: list[list[datetime]] = []
        for price in self.cheap_intervals(day, cheap_hours, mode):  # chronologisch
            if blocks and blocks[-1][1] == price.start:
                blocks[-1][1] = price.end
                blocks[-1][2] = price.start
            else:
                blocks.append([price.start, price.end, price.start])
        return [(start, end, last in surplus) for start, end, last in blocks]

    def jittered_cheap_windows(
        self, day, cheap_hours: float, phase: float, mode: str = DEFAULT_CHEAP_MODE
    ) -> list[tuple[datetime, datetime, bool]]:
        """Gejitterte Schaltfenster der Günstig-Blöcke als ``(on, off, soft_end)``.

        ``phase`` ist der sensoreigene, deterministische Versatz-Wert (siehe
        :func:`.jitter.cheap_phase`). ``soft_end`` zeigt an, dass das Blockende
        gleichstandsbedingt gekappt wurde (Ausschalten nicht in die nächste
        Preiszone). Wirkt ausschließlich für den „Günstige Stunde"-Sensor.
        """
        windows: list[tuple[datetime, datetime, bool]] = []
        for start, end, soft_end in self._cheap_blocks(day, cheap_hours, mode):
            on_time, off_time = jittered_window(start, end, phase, soft_end=soft_end)
            windows.append((on_time, off_time, soft_end))
        return windows

    def is_cheap_now(
        self,
        moment: datetime,
        cheap_hours: float,
        phase: float,
        mode: str = DEFAULT_CHEAP_MODE,
    ) -> bool:
        """Ob ``moment`` in einem gejitterten Günstig-Fenster liegt.

        Geprüft werden die Fenster des aktuellen **und** des vorigen Tages, da
        das Ausschaltfenster des letzten Blocks über Mitternacht hinausreichen
        kann.
        """
        day = dt_util.as_local(moment).date()
        for d in (day - timedelta(days=1), day):
            for on_time, off_time, _ in self.jittered_cheap_windows(
                d, cheap_hours, phase, mode
            ):
                if on_time <= moment < off_time:
                    return True
        return False

    def next_cheap_on(
        self,
        moment: datetime,
        cheap_hours: float,
        phase: float,
        mode: str = DEFAULT_CHEAP_MODE,
    ) -> datetime | None:
        """Nächster gejitterter Einschaltzeitpunkt nach ``moment`` (oder ``None``)."""
        day = dt_util.as_local(moment).date()
        upcoming = [
            on_time
            for d in (day, day + timedelta(days=1))
            for on_time, _, _ in self.jittered_cheap_windows(
                d, cheap_hours, phase, mode
            )
            if on_time > moment
        ]
        return min(upcoming) if upcoming else None


class SmartTimesCoordinator(DataUpdateCoordinator[SmartTimesData]):
    """Koordiniert das Laden der smartENERGY-Preise.

    Die Entitäten werden minütlich neu berechnet (damit der aktuelle Preis
    beim Stundenwechsel sofort stimmt).  Tatsächliche API-Aufrufe erfolgen
    jedoch nur:

    * einmalig beim Start (kein Cache vorhanden),
    * täglich ab ``NEXT_DAY_PRICES_HOUR`` + Jitter (Morgen-Preise holen),
    * alle ``FETCH_RETRY_INTERVAL_MINUTES``, wenn Morgen-Preise noch fehlen
      oder ein Abruf fehlschlug (solange Daten vorhanden sind),
    * sofort, wenn die gecachten Preise den aktuellen Zeitpunkt nicht mehr
      abdecken (z. B. nach Mitternacht ohne Morgen-Daten).

    Das ergibt im Normalbetrieb **einen** API-Aufruf pro Tag.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SmartTimesApiClient,
        include_vat: bool,
        grid_zone: GridZone | None = None,
        handling_fee_net: float = 0.0,
        tariff_name: str | None = None,
    ) -> None:
        """Initialisiert den Koordinator (Recalc-Intervall, Abruf-Jitter, Tarif)."""
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
        # Abwicklungsgebühr (netto, ct/kWh); 0,0 außer bei smartCONTROL.
        self._handling_fee_net = handling_fee_net
        # Anzeige-Tarifname aus der Nutzer-Auswahl (nicht aus der API – diese
        # liefert bei smartCONTROL "EPEXSPOTAT").
        self._tariff_name = tariff_name
        self._last_fetch: datetime | None = None
        self._last_result: SmartTimesResult | None = None
        # Deterministischer Jitter (0..FETCH_JITTER_MINUTES-1 min) aus der
        # Entry-ID: verschiedene HA-Instanzen treffen den API-Server zeitversetzt.
        h = int(hashlib.md5(entry.entry_id.encode()).hexdigest(), 16)
        self._jitter_minutes: int = h % FETCH_JITTER_MINUTES

    @property
    def include_vat(self) -> bool:
        """Ob die Preise inkl. USt. (brutto) ausgewiesen werden."""
        return self._include_vat

    @property
    def last_fetch(self) -> datetime | None:
        """Zeitpunkt des letzten (versuchten) API-Abrufs (für die Diagnose)."""
        return self._last_fetch

    def _needs_fetch(self, now: datetime) -> bool:
        """Entscheidet, ob ein neuer API-Aufruf nötig ist."""
        # Kein Cache → sofort holen (Fehler → UpdateFailed, HA übernimmt Retry)
        if self._last_result is None:
            return True

        prices = self._last_result.prices

        # Cache deckt aktuellen Zeitpunkt nicht mehr ab (z. B. nach Mitternacht)
        if not prices or prices[-1].end <= now:
            return (
                self._last_fetch is None
                or now - self._last_fetch >= timedelta(minutes=FETCH_RETRY_INTERVAL_MINUTES)
            )

        # Morgen-Preise fehlen noch → ab NEXT_DAY_PRICES_HOUR + Jitter holen
        tomorrow = dt_util.as_local(now).date() + timedelta(days=1)
        has_tomorrow = any(
            dt_util.as_local(p.start).date() == tomorrow for p in prices
        )
        if not has_tomorrow:
            local_now = dt_util.as_local(now)
            fetch_threshold = local_now.replace(
                hour=NEXT_DAY_PRICES_HOUR,
                minute=self._jitter_minutes,
                second=0,
                microsecond=0,
            )
            if local_now >= fetch_threshold:
                return (
                    self._last_fetch is None
                    or now - self._last_fetch >= timedelta(minutes=FETCH_RETRY_INTERVAL_MINUTES)
                )

        return False

    async def _async_update_data(self) -> SmartTimesData:
        """Berechnet die Entitätsdaten neu und ruft bei Bedarf die API ab."""
        now = dt_util.now()

        if self._needs_fetch(now):
            try:
                self._last_result = await self._client.async_get_prices()
            except SmartTimesApiError as err:
                if self._last_result is None:
                    raise UpdateFailed(str(err)) from err
                # Frühere Daten behalten, falls ein einzelner Abruf scheitert.
                _LOGGER.warning(
                    "Aktualisierung der smartENERGY-Preise fehlgeschlagen, "
                    "verwende zwischengespeicherte Daten: %s",
                    err,
                )
            finally:
                # Zeitstempel immer setzen – auch bei Fehler – damit
                # _needs_fetch den nächsten Versuch um FETCH_RETRY_INTERVAL
                # verzögert und die API nicht minütlich gespammt wird.
                self._last_fetch = now

        result = self._last_result
        assert result is not None  # nach erfolgreichem ersten Abruf garantiert
        return SmartTimesData(
            # Anzeige-Tarif aus der Nutzer-Auswahl; nur als Fallback der API-Wert.
            tariff=self._tariff_name or result.tariff,
            unit=result.unit,
            interval_minutes=result.interval_minutes,
            include_vat=self._include_vat,
            prices=result.prices,
            basic_fees=result.basic_fees,
            basic_fee_unit=result.basic_fee_unit,
            grid_zone=self._grid_zone,
            handling_fee_net=self._handling_fee_net,
        )
