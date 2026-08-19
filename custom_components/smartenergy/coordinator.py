"""DataUpdateCoordinator für die smartTIMES Integration."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    MarketPrice,
    SmartTimesApiClient,
    SmartTimesApiError,
    SmartTimesApiPermanentError,
    SmartTimesResult,
)
from .api import FeeEntry
from .const import (
    CHEAP_MODE_CONSECUTIVE,
    DEFAULT_CHEAP_MODE,
    DEFAULT_EXACT_HOURS,
    DOMAIN,
    FETCH_FAILURE_REPAIR_HOURS,
    FETCH_JITTER_MINUTES,
    FETCH_RETRY_INTERVAL_MINUTES,
    FETCH_RETRY_MAX_FAILURES_COUNTED,
    FETCH_RETRY_MAX_INTERVAL_MINUTES,
    MIN_FETCH_INTERVAL_MINUTES,
    NEXT_DAY_PRICES_HOUR,
    RECALC_INTERVAL_MINUTES,
    VAT_RATE,
)
from .grid_fees import GridZone
from .jitter import cheap_phase, jittered_window
from .repairs import async_check_tariff_data_year, async_update_fetch_issue
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
        self,
        day,
        cheap_hours: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> tuple[set[datetime], set[datetime]]:
        """``(alle, strikte)`` Startzeiten der günstigsten Intervalle eines Tages.

        ``mode`` steuert die Auswahllogik:

        * ``CHEAP_MODE_INDIVIDUAL`` (Standard): die günstigsten **Einzel**-
          Intervalle des Tages – sie dürfen über den Tag verteilt (zerteilt)
          sein. ``strikte`` enthält **genau** so viele Intervalle, wie
          ``cheap_hours`` ergibt (Gleichstand nach Startzeit aufgelöst).
          ``alle`` enthält zusätzlich die bei Gleichstand am Schwellwert
          mitmarkierten „Überschuss"-Intervalle; mit ``exact_hours`` unterbleibt
          diese Erweiterung und ``alle == strikte`` (siehe
          ``CONF_EXACT_HOURS``).
        * ``CHEAP_MODE_CONSECUTIVE``: ein einziger **zusammenhängender** Block
          „am Stück" – das günstigste lückenlose Zeitfenster aus ``cheap_hours``
          (siehe :meth:`_consecutive_selection`). Hier wird **nie** erweitert,
          die Stundenzahl gilt also immer exakt; ``exact_hours`` ist ohne
          Wirkung.
        """
        prices = self.for_day(day)
        if not prices:
            return set(), set()
        count = min(self._cheap_count(cheap_hours), len(prices))
        if mode == CHEAP_MODE_CONSECUTIVE:
            return self._consecutive_selection(prices, count)
        return self._individual_selection(prices, count, exact_hours)

    def _individual_selection(
        self,
        prices: list[MarketPrice],
        count: int,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> tuple[set[datetime], set[datetime]]:
        """``(alle, strikte)`` für die günstigsten **Einzel**-Intervalle.

        ``strikte`` sind die ``count`` günstigsten Intervalle (Gleichstand nach
        Startzeit aufgelöst). Standardmäßig ergänzt ``alle`` die am Schwellwert
        gleich teuren „Überschuss"-Intervalle, sodass keine gleich günstige
        Stunde fehlt. Mit ``exact_hours`` unterbleibt das: Es bleibt bei genau
        ``count`` Intervallen, die eingestellte Stundenzahl wird also exakt
        eingehalten.
        """
        valued = [(self.all_in_value(p), p) for p in prices]
        ranked = sorted(valued, key=lambda item: (item[0], item[1].start))
        strict_starts = {p.start for _, p in ranked[:count]}
        if exact_hours:
            return set(strict_starts), strict_starts
        cutoff_value = ranked[count - 1][0]
        all_starts = {p.start for value, p in valued if value <= cutoff_value}
        return all_starts, strict_starts

    def _consecutive_selection(
        self, prices: list[MarketPrice], count: int
    ) -> tuple[set[datetime], set[datetime]]:
        """``(alle, strikte)`` für den günstigsten **zusammenhängenden** Block.

        ``strikte`` ist das günstigste lückenlose Fenster aus ``count``
        aufeinanderfolgenden Intervallen (geringste Summe der Gesamtkosten,
        Gleichstand → frühestes Fenster). ``prices`` muss chronologisch sortiert
        sein (wie von :meth:`for_day` geliefert).

        ``alle`` ist hier **identisch** mit ``strikte``: Bei Gleichstand wird
        der Block *nicht* verlängert. Eine feste Fensterlänge ist der Zweck
        dieser Betriebsart – sie ist für Geräte mit fester Laufzeit gedacht
        (Waschmaschine, Geschirrspüler), und genau die hob eine Verlängerung
        auf. Bei smartTIMES etwa, das als Zeittarif nur drei Preisstufen kennt,
        wurde aus einem angeforderten 30-Minuten-Block so ein Block über
        mehrere Stunden. Grenzen preisgleiche Intervalle an, ist die Wahl
        zwischen ihnen ohnehin beliebig – dann gilt das angeforderte Fenster.

        Sollten die Tagesdaten eine Lücke aufweisen und kein lückenloses Fenster
        der geforderten Länge existieren, wird auf die günstigsten
        Einzelintervalle ausgewichen, damit der Sensor nie dauerhaft „aus"
        bleibt. Auch dort wird **nicht** erweitert, damit die Zusage einer
        festen Länge in jedem Pfad dieser Betriebsart gilt.
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
            return self._individual_selection(prices, count, True)

        starts = {
            prices[i].start for i in range(best_index, best_index + count)
        }
        return set(starts), starts

    def _cheap_starts(
        self,
        day,
        cheap_hours: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> set[datetime]:
        """Startzeiten *aller* günstigen Intervalle eines Tages (inkl. Gleichstand)."""
        return self._cheap_selection(day, cheap_hours, mode, exact_hours)[0]

    def cheap_intervals(
        self,
        day,
        cheap_hours: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> list[MarketPrice]:
        """Die günstigsten Intervalle eines Tages (nach Gesamtkosten), chronologisch."""
        starts = self._cheap_starts(day, cheap_hours, mode, exact_hours)
        return [price for price in self.for_day(day) if price.start in starts]

    def cheap_cutoff(
        self,
        day,
        cheap_hours: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> float | None:
        """Höchster Gesamtpreis (ct/kWh) unter den günstigen Intervallen des Tages."""
        intervals = self.cheap_intervals(day, cheap_hours, mode, exact_hours)
        if not intervals:
            return None
        return max(self.all_in_value(p) for p in intervals)

    def _cheap_blocks(
        self,
        day,
        cheap_hours: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> list[tuple[datetime, datetime, bool]]:
        """Günstig-Blöcke eines Tages als ``(start, end, exceeds_cheap_hours)``.

        Direkt aufeinanderfolgende günstige Intervalle werden zu einem Block
        zusammengefasst, damit der Jitter pro **Block** (nicht pro Intervall)
        wirkt – ein durchgehender günstiger Zeitraum wird so nie zerteilt. Im
        Modus ``CHEAP_MODE_CONSECUTIVE`` ist die Auswahl ohnehin bereits ein
        einziger zusammenhängender Block.

        ``exceeds_cheap_hours`` ist ``True``, wenn der Block **mindestens ein**
        „Überschuss"-Intervall enthält: eines, das nur durch die
        Gleichstands-Mechanik am Schwellwert dazukam und damit über die
        konfigurierte Stundenzahl hinausgeht. Das kann folglich nur im
        Einzelstunden-Modus **ohne** ``exact_hours`` vorkommen; sonst ist die
        Angabe immer ``False``.

        Maßgeblich ist der **ganze** Block, nicht sein letztes Intervall: Ein
        Überschuss-Intervall kann genauso am Anfang oder in der Mitte liegen –
        etwa wenn es preisgleich mit dem Schwellwert ist, die darauf folgenden
        Intervalle aber darunter liegen. Die frühere Prüfung nur des letzten
        Intervalls meldete solche Blöcke fälschlich als unauffällig.

        Die Angabe ist rein informativ und wird im Sensor-Attribut
        ``cheap_windows`` ausgewiesen; auf das Schalten wirkt sie sich nicht
        aus. Sie hieß früher ``soft_end`` und steuerte ein vorgezogenes
        Ausschalten, damit ein so verlängerter Block nicht zusätzlich in die
        nächste (teurere) Preiszone ausgreift. Das gilt inzwischen für *jedes*
        Blockende (siehe :func:`.jitter.jittered_window`), weshalb die Angabe
        nichts mehr mit dem Blockende zu tun hat.
        """
        all_starts, strict_starts = self._cheap_selection(
            day, cheap_hours, mode, exact_hours
        )
        surplus = all_starts - strict_starts
        # [start, end, enthält Überschuss-Intervall]
        blocks: list[list] = []
        # Direkt über ``for_day`` (chronologisch) statt über ``cheap_intervals``:
        # Jenes ermittelt die Auswahl über ``_cheap_starts`` ein zweites Mal,
        # obwohl sie hier bereits vorliegt. Der Koordinator rechnet minütlich,
        # und ``_cheap_blocks_spanning`` ruft diese Methode je Auswertung bis zu
        # dreimal – der doppelte Lauf summiert sich entsprechend.
        for price in self.for_day(day):
            if price.start not in all_starts:
                continue
            exceeds = price.start in surplus
            if blocks and blocks[-1][1] == price.start:
                blocks[-1][1] = price.end
                blocks[-1][2] = blocks[-1][2] or exceeds
            else:
                blocks.append([price.start, price.end, exceeds])
        return [(start, end, exceeds) for start, end, exceeds in blocks]

    def _cheap_blocks_spanning(
        self,
        day,
        cheap_hours: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> list[tuple[datetime, datetime, bool]]:
        """Günstig-Blöcke eines Tages, über die Tagesgrenze hinweg zusammengefasst.

        Die *Auswahl* der günstigen Intervalle bleibt bewusst tageweise – jeder
        Kalendertag bekommt seine eigenen ``cheap_hours``. Für den Jitter ist
        Mitternacht aber keine echte Grenze: Läuft ein günstiger Zeitraum über
        den Tageswechsel (im Einzelstunden-Modus der Normalfall, da die Nacht
        meist am günstigsten ist), zerfiele er in zwei getrennt gejitterte
        Blöcke. Deren Fenster stoßen dann nicht mehr aneinander, sondern klaffen
        um ``JITTER_SPAN_SECONDS`` auseinander – und zwar für *jede* Phase
        gleich weit, weil sich beide Flanken um denselben Betrag verschieben:
        Der Vortagsblock schaltet um die volle Breite vorgezogen ab, der
        Folgeblock um dieselbe Breite verzögert ein. Ohne Jitter gäbe es die
        Lücke nicht (beide Grenzen fallen exakt auf Mitternacht); erst der
        Jitter reißt sie auf und erzeugt so genau den Aus-/Einschaltzyklus, den
        er verhindern soll.

        Angrenzende Blöcke zweier Tage werden deshalb hier zu einem
        zusammengefasst. Das geschieht **symmetrisch**: Ein verschmolzener Block
        erscheint identisch im Ergebnis beider beteiligten Tage, sodass es
        keine Rolle spielt, über welchen Tag ein Aufrufer ihn findet.

        Zusammengefasst wird jeweils ein Tag nach vorn und einer nach hinten.
        Ein Block über drei Kalendertage hinweg setzte einen vollständig
        günstigen Tag voraus (``cheap_hours`` = 24) und käme praktisch nicht
        vor; er wird von dem Tag aus, der ihn enthält, dennoch vollständig
        aufgelöst.

        Fehlen die Preise des Nachbartages noch – die Morgen-Preise stehen erst
        ab ``NEXT_DAY_PRICES_HOUR`` bereit –, gibt es nichts zusammenzufassen:
        Der Block wird dann wie bisher an der Tagesgrenze gejittert und rückt
        mit dem nächsten Abruf zusammen.
        """
        blocks = self._cheap_blocks(day, cheap_hours, mode, exact_hours)
        if not blocks:
            return blocks
        # Nur ein Block, der eine Tagesgrenze exakt berührt, kann überhaupt an
        # den Nachbartag angrenzen. Ohne diese Vorprüfung liefe die (im
        # Blockmodus nicht ganz billige) Auswahl an jedem Tag dreifach.
        if blocks[0][0] == dt_util.start_of_local_day(day):
            previous = self._cheap_blocks(
                day - timedelta(days=1), cheap_hours, mode, exact_hours
            )
            if previous and previous[-1][1] == blocks[0][0]:
                # ``exceeds_cheap_hours`` verodern: Es gilt für den gesamten
                # zusammengefassten Block, also auch, wenn nur der Teil aus dem
                # Nachbartag Überschuss-Intervalle beisteuert.
                blocks[0] = (
                    previous[-1][0],
                    blocks[0][1],
                    previous[-1][2] or blocks[0][2],
                )
        if blocks[-1][1] == dt_util.start_of_local_day(day + timedelta(days=1)):
            following = self._cheap_blocks(
                day + timedelta(days=1), cheap_hours, mode, exact_hours
            )
            if following and following[0][0] == blocks[-1][1]:
                blocks[-1] = (
                    blocks[-1][0],
                    following[0][1],
                    blocks[-1][2] or following[0][2],
                )
        return blocks

    def jittered_cheap_windows(
        self,
        day,
        cheap_hours: float,
        phase: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> list[tuple[datetime, datetime, bool]]:
        """Schaltfenster der Blöcke als ``(on, off, exceeds_cheap_hours)``.

        ``phase`` ist der sensoreigene, deterministische Versatz-Wert (siehe
        :func:`.jitter.cheap_phase`). Wirkt ausschließlich für den „Günstige
        Stunde"-Sensor.

        ``exceeds_cheap_hours`` ist rein informativ: Es zeigt an, dass der Block
        durch die Gleichstands-Mechanik über die konfigurierte Stundenzahl
        hinaus reicht (siehe :meth:`_cheap_blocks`). Auf das Schalten wirkt es
        sich nicht aus – da beide Flanken nach innen wandern, greift **kein**
        Block in die nächste Preiszone aus.

        Grundlage sind die über die Tagesgrenze zusammengefassten Blöcke (siehe
        :meth:`_cheap_blocks_spanning`); ein Fenster kann daher vor ``day``
        beginnen oder nach ``day`` enden.
        """
        windows: list[tuple[datetime, datetime, bool]] = []
        for start, end, exceeds in self._cheap_blocks_spanning(
            day, cheap_hours, mode, exact_hours
        ):
            on_time, off_time = jittered_window(start, end, phase)
            windows.append((on_time, off_time, exceeds))
        return windows

    def is_cheap_now(
        self,
        moment: datetime,
        cheap_hours: float,
        phase: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> bool:
        """Ob ``moment`` in einem gejitterten Günstig-Fenster liegt.

        Geprüft werden die Fenster des aktuellen **und** des vorigen Tages, da
        das Ausschaltfenster des letzten Blocks über Mitternacht hinausreichen
        kann. Ein über den Tageswechsel zusammengefasster Block (siehe
        :meth:`_cheap_blocks_spanning`) ist damit ebenfalls abgedeckt: Er
        erscheint bereits im Ergebnis des Tages von ``moment`` selbst.
        """
        day = dt_util.as_local(moment).date()
        for d in (day - timedelta(days=1), day):
            for on_time, off_time, _ in self.jittered_cheap_windows(
                d, cheap_hours, phase, mode, exact_hours
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
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> datetime | None:
        """Nächster gejitterter Einschaltzeitpunkt nach ``moment`` (oder ``None``)."""
        day = dt_util.as_local(moment).date()
        upcoming = [
            on_time
            for d in (day, day + timedelta(days=1))
            for on_time, _, _ in self.jittered_cheap_windows(
                d, cheap_hours, phase, mode, exact_hours
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
    * nach ``FETCH_RETRY_INTERVAL_MINUTES``, wenn Morgen-Preise noch fehlen
      oder ein Abruf fehlschlug (solange Daten vorhanden sind) – mit jedem
      weiteren erfolglosen Versuch verdoppelt sich diese Wartezeit bis
      ``FETCH_RETRY_MAX_INTERVAL_MINUTES``,
    * sofort, wenn die gecachten Preise den aktuellen Zeitpunkt nicht mehr
      abdecken (z. B. nach Mitternacht ohne Morgen-Daten).

    Das ergibt im Normalbetrieb **einen** API-Aufruf pro Tag. Unabhängig von
    diesen Bedingungen begrenzt ``_fetch_allowed`` den Abstand zweier Aufrufe
    auf mindestens ``MIN_FETCH_INTERVAL_MINUTES`` – eine Bremse, die im
    Normalbetrieb nie greift, aber verhindert, dass ein Fehler in der obigen
    Logik die API im Minutentakt trifft.
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
        self._last_success: datetime | None = None
        self._last_result: SmartTimesResult | None = None
        # Zähler erfolgloser Versuche (steuert die wachsende Wartezeit) und die
        # zuletzt vom Server per Retry-After angeforderte Pause.
        self._failed_attempts: int = 0
        self._retry_after: timedelta | None = None
        # Seed des täglichen Abruf-Jitters (siehe `_jitter_minutes`).
        self._entry_id = entry.entry_id

    @property
    def include_vat(self) -> bool:
        """Ob die Preise inkl. USt. (brutto) ausgewiesen werden."""
        return self._include_vat

    @property
    def last_fetch(self) -> datetime | None:
        """Zeitpunkt des letzten (versuchten) API-Abrufs (für die Diagnose)."""
        return self._last_fetch

    def _has_tomorrow_prices(self, now: datetime) -> bool:
        """Ob der Cache bereits Preise für den morgigen Kalendertag enthält."""
        if self._last_result is None:
            return False
        tomorrow = dt_util.as_local(now).date() + timedelta(days=1)
        return any(
            dt_util.as_local(price.start).date() == tomorrow
            for price in self._last_result.prices
        )

    def _jitter_minutes(self, now: datetime) -> int:
        """Minuten-Versatz des täglichen Abrufs (0..FETCH_JITTER_MINUTES-1).

        Verteilt die Abrufe verschiedener HA-Instanzen über ein Zeitfenster,
        damit der API-Server nicht alle gleichzeitig empfängt. Der Wert ist
        deterministisch aus Entry-ID **und Kalendertag** abgeleitet:

        * **Innerhalb eines Tages konstant** – sonst würde die Schwelle in
          :meth:`_next_day_prices_due` bei jeder minütlichen Neuberechnung
          springen und den Abruf faktisch auf die früheste Minute ziehen.
        * **Von Tag zu Tag wechselnd** – ein über Jahre gleichbleibender
          Versatz wäre zusammen mit dem User-Agent ein wiedererkennbares
          Zeitmuster, das aus Sicht des Servers auch einen Wechsel der
          IP-Adresse überdauert. Der Tagesanteil im Seed nimmt dem Muster diese
          Langlebigkeit, ohne die Lastverteilung zu verändern.
        """
        day = dt_util.as_local(now).date().isoformat()
        return int(cheap_phase(f"{self._entry_id}:{day}") * FETCH_JITTER_MINUTES)

    def _next_day_prices_due(self, now: datetime) -> bool:
        """Ob die Morgen-Preise laut API-Zeitplan bereits vorliegen sollten.

        Maßgeblich ist ``NEXT_DAY_PRICES_HOUR`` (Ortszeit) zuzüglich des
        Tages-Jitters dieser Instanz.
        """
        local_now = dt_util.as_local(now)
        threshold = local_now.replace(
            hour=NEXT_DAY_PRICES_HOUR,
            minute=self._jitter_minutes(now),
            second=0,
            microsecond=0,
        )
        return local_now >= threshold

    def _retry_delay(self) -> timedelta:
        """Wartezeit, die zwischen zwei Abruf-Versuchen liegen muss.

        Der erste Wiederholungsversuch erfolgt nach
        ``FETCH_RETRY_INTERVAL_MINUTES``; ab dem zweiten erfolglosen Versuch
        verdoppelt sich die Wartezeit bis höchstens
        ``FETCH_RETRY_MAX_INTERVAL_MINUTES``. Eine per ``Retry-After``
        angeforderte Pause hat Vorrang, sofern sie *länger* ist – eine kürzere
        Vorgabe zu übernehmen widerspräche dem Zweck der Drosselung.
        """
        doublings = max(0, self._failed_attempts - 1)
        minutes = min(
            FETCH_RETRY_INTERVAL_MINUTES * 2**doublings,
            FETCH_RETRY_MAX_INTERVAL_MINUTES,
        )
        delay = timedelta(minutes=minutes)
        if self._retry_after is not None:
            return max(delay, self._retry_after)
        return delay

    def _retry_due(self, now: datetime) -> bool:
        """Ob seit dem letzten Versuch die Wartezeit aus ``_retry_delay`` verstrich."""
        return (
            self._last_fetch is None or now - self._last_fetch >= self._retry_delay()
        )

    def _note_failed_attempt(self, retry_after: timedelta | None = None) -> None:
        """Vermerkt einen erfolglosen Versuch und verlängert damit die Wartezeit."""
        self._failed_attempts = min(
            self._failed_attempts + 1, FETCH_RETRY_MAX_FAILURES_COUNTED
        )
        self._retry_after = retry_after

    def _needs_fetch(self, now: datetime) -> bool:
        """Entscheidet, ob ein neuer API-Aufruf nötig ist."""
        # Kein Cache → sofort holen (Fehler → UpdateFailed, HA übernimmt Retry).
        # `_retry_due` liefert bei noch nie erfolgtem Abruf ebenfalls True, der
        # erste Versuch bleibt also unverzögert; für den – über HA-Setup und
        # Entitäten-Registrierung derzeit nicht erreichbaren – Fall eines
        # weiteren Aufrufs ohne Cache gilt damit dieselbe wachsende Wartezeit
        # wie sonst und nicht nur MIN_FETCH_INTERVAL_MINUTES.
        if self._last_result is None:
            return self._retry_due(now)

        prices = self._last_result.prices

        # Cache deckt aktuellen Zeitpunkt nicht mehr ab (z. B. nach Mitternacht)
        if not prices or prices[-1].end <= now:
            return self._retry_due(now)

        # Morgen-Preise fehlen noch → ab NEXT_DAY_PRICES_HOUR + Jitter holen
        if not self._has_tomorrow_prices(now) and self._next_day_prices_due(now):
            return self._retry_due(now)

        return False

    def _fetch_allowed(self, now: datetime) -> bool:
        """Ob seit dem letzten Abruf-Versuch die Mindestwartezeit verstrichen ist.

        Bewusst unabhängig von ``_needs_fetch``: Jenes entscheidet fachlich, *ob*
        neue Daten nötig sind, diese Bremse begrenzt davon losgelöst, *wie oft*
        die API überhaupt angefragt werden darf (siehe
        ``MIN_FETCH_INTERVAL_MINUTES``). Beide Bedingungen müssen erfüllt sein.
        """
        if self._last_fetch is None:
            return True
        return now - self._last_fetch >= timedelta(minutes=MIN_FETCH_INTERVAL_MINUTES)

    def _fetch_failing(self, now: datetime) -> bool:
        """Ob seit ``FETCH_FAILURE_REPAIR_HOURS`` kein Abruf mehr gelang.

        Maßgeblich ist der letzte *erfolgreiche* Abruf (``_last_success``):
        Erst wenn er so lange zurückliegt, sind die zwischengespeicherten
        Preise vermutlich veraltet und ein Repair-Issue gerechtfertigt (siehe
        ``repairs.async_update_fetch_issue``).
        """
        if self._last_success is None:
            return False
        return now - self._last_success >= timedelta(hours=FETCH_FAILURE_REPAIR_HOURS)

    async def _async_update_data(self) -> SmartTimesData:
        """Berechnet die Entitätsdaten neu und ruft bei Bedarf die API ab."""
        now = dt_util.now()

        if self._needs_fetch(now) and self._fetch_allowed(now):
            try:
                self._last_result = await self._client.async_get_prices()
            except SmartTimesApiError as err:
                if isinstance(err, SmartTimesApiPermanentError):
                    # Dauerhafte Ablehnung: direkt auf die maximale Wartezeit
                    # gehen, statt sich in kurzen Schritten dorthin zu zählen.
                    self._failed_attempts = FETCH_RETRY_MAX_FAILURES_COUNTED
                    self._retry_after = err.retry_after
                else:
                    self._note_failed_attempt(err.retry_after)
                if self._last_result is None:
                    raise UpdateFailed(str(err)) from err
                # Frühere Daten behalten, falls ein einzelner Abruf scheitert.
                _LOGGER.warning(
                    "Aktualisierung der smartENERGY-Preise fehlgeschlagen, "
                    "verwende zwischengespeicherte Daten (nächster Versuch in "
                    "%d Minuten): %s",
                    self._retry_delay() // timedelta(minutes=1),
                    err,
                )
            else:
                self._last_success = now
                if self._next_day_prices_due(now) and not self._has_tomorrow_prices(
                    now
                ):
                    # Der Abruf gelang, die Morgen-Preise waren aber noch nicht
                    # veröffentlicht. Auch das ist ein erfolgloser Versuch – der
                    # nächste erfolgt daher in größerem Abstand.
                    self._note_failed_attempt()
                else:
                    self._failed_attempts = 0
                    self._retry_after = None
            finally:
                # Zeitstempel immer setzen – auch bei Fehler – damit
                # _needs_fetch den nächsten Versuch um _retry_delay() verzögert
                # und die API nicht minütlich gespammt wird.
                self._last_fetch = now

            # Repair-Issues nur dort prüfen, wo sich die maßgeblichen
            # Zeitstempel überhaupt ändern können (= bei einem Abruf-Versuch,
            # siehe oben) – das genügt für eine zeitnahe Meldung/Schließung,
            # ohne die Issue-Registry minütlich anzustoßen.
            async_check_tariff_data_year(self.hass, now)
            async_update_fetch_issue(self.hass, failing=self._fetch_failing(now))

        result = self._last_result
        if result is None:
            # Erreichbar, solange noch kein Abruf gelungen ist – etwa wenn die
            # Mindestwartezeit einen erneuten Versuch gerade bremst. Dann gibt es
            # schlicht noch nichts anzuzeigen; HA wiederholt die Aktualisierung.
            raise UpdateFailed("Es liegen noch keine Preisdaten vor")
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
