"""DataUpdateCoordinator für die smartTIMES Integration."""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    FeeEntry,
    MarketPrice,
    SmartTimesApiClient,
    SmartTimesApiError,
    SmartTimesApiPermanentError,
    SmartTimesResult,
)
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
    QUANTILE_DECIMALS,
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


@dataclass(frozen=True, slots=True)
class PriceRank:
    """Einordnung eines Intervalls in die Gesamtpreise seines Kalendertages.

    Bezugsgröße ist der **Gesamtpreis** (:meth:`SmartTimesData.all_in_value`),
    wie bei allen übrigen Tageskennzahlen und bei der Günstig-Stunden-Auswahl.
    Nach dem reinen Arbeitspreis fiele die Reihenfolge anders aus: Das
    SNAP-Fenster (Sommer, 10-16 Uhr) senkt das Netzentgelt und spaltet damit
    eine Arbeitspreis-Stufe in zwei verschieden teure Hälften.
    """

    rank: int
    """Rangplatz, 1 = günstigstes Intervall des Tages.

    Gleich teure Intervalle tragen denselben Rang (Wettkampfregel „1224“); die
    nächste Preisstufe überspringt die dabei verbrauchten Plätze. Sind etwa die
    n günstigsten Intervalle preisgleich, tragen alle Rang 1 und die nächste
    Stufe beginnt bei n + 1.
    """

    count: int
    """Intervalle des Kalendertages insgesamt (96 bei Viertelstunden)."""

    cheaper: int
    """Echt günstigere Intervalle desselben Tages."""

    equal: int
    """Gleich teure Intervalle, das eigene eingeschlossen (also mindestens 1)."""

    quantile: float
    """Mittelrang-Quantil in Prozent: je niedriger, desto günstiger.

    ``(cheaper + equal / 2) / count``. Der Mittelrang teilt einen Gleichstand
    hälftig und ist dadurch **symmetrisch**: Der Tagesdurchschnitt liegt immer
    bei genau 50 %. Genau das leisten die naheliegenden Varianten nicht –
    „Anteil kleiner gleich“ und „Anteil echt kleiner“ verschieben den
    Durchschnitt um eine halbe Gleichstandsbreite nach oben bzw. unten.

    **0 % und 100 % kommen nie vor.** Das günstigste Preisniveau liegt bei der
    halben Breite seiner Gleichstandsgruppe: bei 96 lauter verschiedenen
    Viertelstunden also bei 0,52 %, bei drei Stufen zu je 32 dagegen schon bei
    16,67 %. Eine Schwelle wählt deshalb **nicht** garantiert den gleich großen
    Anteil des Tages – „unter 25 %“ trifft im zweiten Fall die ganze günstigste
    Stufe und damit ein Drittel des Tages. Wer eine feste Laufzeit braucht,
    nimmt den Günstige-Stunde-Sensor, nicht eine Quantil-Schwelle.
    """


@dataclass(slots=True)
class SmartTimesData:
    """Aufbereitete Daten, die der Koordinator den Entitäten bereitstellt.

    Die Felder sind nach dem Erzeugen unveränderlich – mit **einer bewussten
    Ausnahme**: den privaten ``*_cache``-Feldern am Ende. Sie halten rein
    abgeleitete Zwischenergebnisse und sind deshalb aus ``__eq__``/``__repr__``
    ausgenommen (``compare=False``/``repr=False``).

    Der Cache ist nötig, weil der Koordinator **minütlich** neu rechnet und
    jeder „Günstige Stunde“-Sensor seine Auswahl in den *synchronen* Properties
    ``is_on``/``extra_state_attributes`` zieht – die Rechenzeit fällt also im
    Event-Loop von Home Assistant an. Ohne Cache wurde dieselbe Tagesauswahl je
    Auswertung vielfach neu gebildet: ``is_cheap_now`` wertet zwei Tage aus,
    ``_cheap_blocks_spanning`` je Tag bis zu drei.

    Die Caches halten ausschließlich **unveränderliche** Container (``tuple``,
    ``frozenset``). Ein Aufrufer kann eine gecachte Sammlung damit nicht aus
    Versehen verändern und so die Daten aller Sensoren derselben Instanz
    verfälschen – die Zusage steht im Typ statt in einem Kommentar. Wer eine
    veränderbare Fassung braucht, baut sie sich selbst (siehe
    :meth:`_cheap_blocks_spanning`).

    Eine Invalidierung braucht es nicht: Der Koordinator erzeugt in
    ``_async_update_data`` bei jeder Neuberechnung eine **frische** Instanz. Der
    Cache lebt damit genau so lange wie die Daten, die er beschreibt. Alle
    Sensoren lesen dieselbe ``coordinator.data``; gleich konfigurierte Sensoren
    teilen sich das Ergebnis zusätzlich. Sperren sind unnötig –
    Entitäts-Properties und Koordinator laufen beide im Event-Loop, also
    einfädig.
    """

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

    # --- Rechen-Cache (abgeleitet, siehe Klassen-Docstring) ---------------- #
    # Preis-Einträge je lokalem Kalendertag (spart den Durchlauf aller Preise
    # samt `as_local` je Aufruf).
    _day_price_cache: dict[date, tuple[MarketPrice, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    # Gesamtpreis je Intervall. Schlüssel ist Startzeitpunkt **und** Bruttopreis
    # – so trifft ein Eintrag, der nicht aus `prices` stammt, nie einen fremden
    # Wert.
    _value_cache: dict[tuple[datetime, float], float] = field(
        default_factory=dict, repr=False, compare=False
    )
    # Günstig-Auswahl bzw. -Blöcke je (Tag, Stundenzahl, Modus, exact_hours).
    # Der Jitter geht bewusst *nicht* in den Schlüssel ein: Er wirkt erst auf
    # die fertigen Blöcke, sodass sich Sensoren mit gleicher Einstellung die
    # Auswahl teilen.
    _selection_cache: dict[
        tuple[date, float, str, bool], tuple[frozenset[datetime], frozenset[datetime]]
    ] = field(default_factory=dict, repr=False, compare=False)
    _block_cache: dict[
        tuple[date, float, str, bool], tuple[tuple[datetime, datetime, bool], ...]
    ] = field(default_factory=dict, repr=False, compare=False)

    def current(self, moment: datetime | None = None) -> MarketPrice | None:
        """Der für ``moment`` (Standard: jetzt) gültige Preis-Eintrag."""
        moment = moment or dt_util.now()
        for price in self.prices:
            if price.start <= moment < price.end:
                return price
        return None

    def for_day(self, day) -> tuple[MarketPrice, ...]:
        """Alle Preis-Einträge eines bestimmten lokalen Kalendertages.

        Wird je Tag einmal gebildet und danach aus dem Cache geliefert; das
        Ergebnis ist deshalb ein Tupel und nicht zu verändern (siehe
        Klassen-Docstring).
        """
        prices = self._day_price_cache.get(day)
        if prices is None:
            prices = tuple(
                price
                for price in self.prices
                if dt_util.as_local(price.start).date() == day
            )
            self._day_price_cache[day] = prices
        return prices

    def has_prices_for(self, day) -> bool:
        """Ob für diesen lokalen Kalendertag überhaupt Preise vorliegen.

        Nutzt den Tages-Cache aus :meth:`for_day`, kostet also nichts über den
        ohnehin nötigen Durchlauf hinaus.

        Das Gegenstück im Koordinator (``_has_tomorrow_prices``) bleibt bewusst
        eigenständig: Es läuft, bevor diese Datenklasse überhaupt gebaut ist.
        """
        return bool(self.for_day(day))

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

        Das Ergebnis wird je Instanz zwischengespeichert (siehe Klassen-
        Docstring): Die Auswahllogik vergleicht dieselben Intervalle vielfach,
        die Rechnung selbst (zwei ``as_local``, Abgaben-Tabelle, Netzentgelt,
        Rundung) ist dabei jedes Mal dieselbe.
        """
        key = (price.start, price.gross_ct_per_kwh)
        value = self._value_cache.get(key)
        if value is None:
            value = self._compute_all_in_value(price)
            self._value_cache[key] = value
        return value

    def _compute_all_in_value(self, price: MarketPrice) -> float:
        """Berechnet den Gesamtpreis eines Eintrags (ohne Cache)."""
        net = price.net_ct_per_kwh + self._surcharges_net(price.start)
        return round(self._apply_vat(net), 4)

    def price_rank(self, moment: datetime | None = None) -> PriceRank | None:
        """Einordnung des laufenden Intervalls in die Gesamtpreise seines Tages.

        ``None``, solange kein Intervall läuft – etwa kurz nach einem Neustart
        oder wenn für den Zeitpunkt keine Preise vorliegen. Die Sensoren stehen
        dann auf „unbekannt“, statt eine Einordnung ohne Grundlage zu melden.

        Der Kalendertag wird aus dem **Intervall** abgeleitet, nicht aus
        ``moment``: Nur so gehört das Intervall garantiert zu genau dem Tag, mit
        dem es verglichen wird.

        Eine eigene Zwischenspeicherung braucht es nicht. Die teuren Teile –
        :meth:`for_day` und :meth:`all_in_value` – sind bereits gecacht; was
        bleibt, ist ein Durchlauf über die Tageswerte, den die Sensoren wenige
        Male je Minute anstoßen.

        Nachgemessen an einem vollen smartCONTROL-Tag (96 Viertelstunden,
        Netzgebiet Wien, jeweils frischer Cache): Alles, was die Sensoren je
        Minute an Kennzahlen anfordern – dreimal die Tageskennzahlen für
        ``average``/``lowest``/``highest`` und viermal diese Methode für Rang
        und Quantil – kostet zusammen rund 0,6 ms. Das ist ein Tausendstel
        Prozent der Minute; ein weiterer Cache verdiente seine Zeilen nicht.
        """
        price = self.current(moment)
        if price is None:
            return None

        day = dt_util.as_local(price.start).date()
        prices = self.for_day(day)
        if not prices:
            return None

        value = self.all_in_value(price)
        values = [self.all_in_value(entry) for entry in prices]

        # Exakter Vergleich ist hier richtig, weil `_compute_all_in_value` jedes
        # Ergebnis auf vier Nachkommastellen rundet: Zwei gleich teure
        # Intervalle landen damit auf demselben Float, auch wenn die Summe auf
        # verschiedenen Wegen zustande kam. Auf den Rechenweg allein wäre kein
        # Verlass – zwei Intervalle können denselben Preis über eine andere
        # Tarifstufe *und* einen anderen SNAP-Zustand erreichen, die sich
        # gegenseitig aufheben. In Wien liegt "Shoulder im SNAP" nur
        # 0,024 ct/kWh über "Off-Peak außerhalb", weil die SNAP-Ersparnis (1,40
        # netto) die Stufenlücke (1,42 netto) fast genau ausgleicht. Eine
        # Toleranz verschmölze umgekehrt Preisstufen, die der Tarif bewusst
        # trennt – und verschenkte den günstigeren Zeitpunkt.
        cheaper = sum(1 for other in values if other < value)
        equal = sum(1 for other in values if other == value)

        return PriceRank(
            rank=cheaper + 1,
            count=len(values),
            cheaper=cheaper,
            equal=equal,
            quantile=round(
                (cheaper + equal / 2) / len(values) * 100, QUANTILE_DECIMALS
            ),
        )

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
        # Intervallen) die zugesagte „mindestens so viele Intervalle“-Semantik
        # eingehalten wird, statt zu wenige Intervalle zu markieren.
        return max(1, math.ceil(cheap_hours * per_hour))

    def _cheap_selection(
        self,
        day,
        cheap_hours: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> tuple[frozenset[datetime], frozenset[datetime]]:
        """``(alle, strikte)`` Startzeiten der günstigsten Intervalle eines Tages.

        ``mode`` steuert die Auswahllogik:

        * ``CHEAP_MODE_INDIVIDUAL`` (Standard): die günstigsten **Einzel**-
          Intervalle des Tages – sie dürfen über den Tag verteilt (zerteilt)
          sein. ``strikte`` enthält **genau** so viele Intervalle, wie
          ``cheap_hours`` ergibt (Gleichstand nach Startzeit aufgelöst).
          ``alle`` enthält zusätzlich die bei Gleichstand am Schwellwert
          mitmarkierten „Überschuss“-Intervalle; mit ``exact_hours`` unterbleibt
          diese Erweiterung und ``alle == strikte`` (siehe
          ``CONF_EXACT_HOURS``).
        * ``CHEAP_MODE_CONSECUTIVE``: ein einziger **zusammenhängender** Block
          „am Stück“ – das günstigste lückenlose Zeitfenster aus ``cheap_hours``
          (siehe :meth:`_consecutive_selection`). Hier wird **nie** erweitert,
          die Stundenzahl gilt also immer exakt; ``exact_hours`` ist ohne
          Wirkung.

        Das Ergebnis wird je ``(Tag, Stundenzahl, Modus, exact_hours)``
        zwischengespeichert (siehe Klassen-Docstring) und ist deshalb
        unveränderlich.
        """
        key = (day, cheap_hours, mode, exact_hours)
        selection = self._selection_cache.get(key)
        if selection is None:
            selection = self._compute_cheap_selection(
                day, cheap_hours, mode, exact_hours
            )
            self._selection_cache[key] = selection
        return selection

    def _compute_cheap_selection(
        self,
        day,
        cheap_hours: float,
        mode: str,
        exact_hours: bool,
    ) -> tuple[frozenset[datetime], frozenset[datetime]]:
        """Ermittelt die Auswahl eines Tages – ohne Cache.

        Siehe :meth:`_cheap_selection` für Bedeutung und Schlüssel.
        """
        prices = self.for_day(day)
        if not prices:
            return frozenset(), frozenset()
        count = min(self._cheap_count(cheap_hours), len(prices))
        if mode == CHEAP_MODE_CONSECUTIVE:
            return self._consecutive_selection(prices, count)
        return self._individual_selection(prices, count, exact_hours)

    def _individual_selection(
        self,
        prices: Sequence[MarketPrice],
        count: int,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> tuple[frozenset[datetime], frozenset[datetime]]:
        """``(alle, strikte)`` für die günstigsten **Einzel**-Intervalle.

        ``strikte`` sind die ``count`` günstigsten Intervalle (Gleichstand nach
        Startzeit aufgelöst). Standardmäßig ergänzt ``alle`` die am Schwellwert
        gleich teuren „Überschuss“-Intervalle, sodass keine gleich günstige
        Stunde fehlt. Mit ``exact_hours`` unterbleibt das: Es bleibt bei genau
        ``count`` Intervallen, die eingestellte Stundenzahl wird also exakt
        eingehalten.
        """
        valued = [(self.all_in_value(p), p) for p in prices]
        ranked = sorted(valued, key=lambda item: (item[0], item[1].start))
        strict_starts = frozenset(p.start for _, p in ranked[:count])
        if exact_hours:
            # Beide Mengen sind unveränderlich, dieselbe zweimal zu liefern ist
            # daher unbedenklich.
            return strict_starts, strict_starts
        cutoff_value = ranked[count - 1][0]
        all_starts = frozenset(
            p.start for value, p in valued if value <= cutoff_value
        )
        return all_starts, strict_starts

    def _consecutive_selection(
        self, prices: Sequence[MarketPrice], count: int
    ) -> tuple[frozenset[datetime], frozenset[datetime]]:
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
        Einzelintervalle ausgewichen, damit der Sensor nie dauerhaft „aus“
        bleibt. Auch dort wird **nicht** erweitert, damit die Zusage einer
        festen Länge in jedem Pfad dieser Betriebsart gilt.

        Gesucht wird über **Präfixsummen**, die Kosten eines Fensters sind also
        eine Differenz statt einer Summe über ``count`` Einträge. Das senkt den
        Aufwand von O(n·count) auf O(n) – bei 96 Intervallen und 4 h waren das
        bisher 96 Fensterpositionen × 16 Intervalle, und zwar je Sensor und
        Minute.
        """
        n = len(prices)
        values = [self.all_in_value(p) for p in prices]
        prefix = [0.0] * (n + 1)
        for i, value in enumerate(values):
            prefix[i + 1] = prefix[i] + value
        # ``run_start[j]`` ist der Beginn des lückenlosen Laufs, der bei ``j``
        # endet. Ein Fenster ab ``i`` hängt damit genau dann zusammen (keine
        # Lücke, ist also wirklich „am Stück“), wenn der Lauf seines letzten
        # Intervalls spätestens bei ``i`` beginnt.
        run_start = [0] * n
        for j in range(1, n):
            run_start[j] = (
                run_start[j - 1] if prices[j - 1].end == prices[j].start else j
            )
        best_total: float | None = None
        best_index = 0
        for i in range(n - count + 1):
            if run_start[i + count - 1] > i:
                continue
            # Die Differenz zweier Präfixsummen weicht in den letzten Bits von
            # der Direktsumme ab; die Toleranz unten (1e-9) liegt weit darüber
            # (auf 4 Nachkommastellen gerundete Werte, höchstens 96 Summanden).
            total = prefix[i + count] - prefix[i]
            if best_total is None or total < best_total - 1e-9:
                best_total = total
                best_index = i
        if best_total is None:
            return self._individual_selection(prices, count, True)

        starts = frozenset(
            prices[i].start for i in range(best_index, best_index + count)
        )
        return starts, starts

    def _cheap_starts(
        self,
        day,
        cheap_hours: float,
        mode: str = DEFAULT_CHEAP_MODE,
        exact_hours: bool = DEFAULT_EXACT_HOURS,
    ) -> frozenset[datetime]:
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
    ) -> tuple[tuple[datetime, datetime, bool], ...]:
        """Günstig-Blöcke eines Tages als ``(start, end, exceeds_cheap_hours)``.

        Direkt aufeinanderfolgende günstige Intervalle werden zu einem Block
        zusammengefasst, damit der Jitter pro **Block** (nicht pro Intervall)
        wirkt – ein durchgehender günstiger Zeitraum wird so nie zerteilt. Im
        Modus ``CHEAP_MODE_CONSECUTIVE`` ist die Auswahl ohnehin bereits ein
        einziger zusammenhängender Block.

        ``exceeds_cheap_hours`` ist ``True``, wenn der Block **mindestens ein**
        „Überschuss“-Intervall enthält: eines, das nur durch die
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

        Das Ergebnis wird je ``(Tag, Stundenzahl, Modus, exact_hours)``
        zwischengespeichert (siehe Klassen-Docstring): ``_cheap_blocks_spanning``
        ruft diese Methode je Auswertung für bis zu drei Tage auf, und
        ``is_cheap_now``/``next_cheap_on`` werten je zwei Tage aus – dieselben
        Tage also mehrfach. Das Ergebnis ist deshalb ein Tupel und nicht zu
        verändern.
        """
        key = (day, cheap_hours, mode, exact_hours)
        blocks = self._block_cache.get(key)
        if blocks is None:
            blocks = self._compute_cheap_blocks(day, cheap_hours, mode, exact_hours)
            self._block_cache[key] = blocks
        return blocks

    def _compute_cheap_blocks(
        self,
        day,
        cheap_hours: float,
        mode: str,
        exact_hours: bool,
    ) -> tuple[tuple[datetime, datetime, bool], ...]:
        """Bildet die Blöcke eines Tages (ohne Cache, siehe :meth:`_cheap_blocks`)."""
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
        return tuple((start, end, exceeds) for start, end, exceeds in blocks)

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
        # Veränderbare Arbeitskopie: Unten werden Randblöcke ersetzt,
        # ``_cheap_blocks`` liefert seinen Tagesstand aber unveränderlich aus dem
        # Cache (siehe Klassen-Docstring).
        blocks = list(self._cheap_blocks(day, cheap_hours, mode, exact_hours))
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
        Stunde“-Sensor.

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
        # Zuletzt von der API gemeldete Einheit der Grundgebühr – die letzte
        # *vorhandene*, nicht die des vorigen Abrufs (siehe
        # `_pruefe_grundgebuehr_einheit`).
        self._letzte_grundgebuehr_einheit: str | None = None
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
        """Ob der Cache bereits Preise für den morgigen Kalendertag enthält.

        Prüft bewusst das rohe Abruf-Ergebnis und nicht ``self.data``: Die
        Methode steuert den Abruf und läuft damit, bevor die
        ``SmartTimesData``-Instanz dieses Durchlaufs existiert – beim ersten
        Lauf ist ``self.data`` sogar ``None``. Die Entitäts-Ebene benutzt
        stattdessen :meth:`SmartTimesData.has_prices_for`; dass beide Sichten
        übereinstimmen, sichert ein Test ab.
        """
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

    def next_day_prices_expected_after(self, now: datetime) -> datetime:
        """Zeitpunkt, ab dem die Morgen-Preise vorliegen sollten (Ortszeit).

        ``NEXT_DAY_PRICES_HOUR`` zuzüglich des Tages-Jitters dieser Instanz.
        Vor diesem Zeitpunkt ist ein leerer Morgen-Tag planmäßig, danach ein
        Hinweis auf eine Störung beim Anbieter.

        Öffentlich, weil der Diagnose-Sensor „Preise für morgen verfügbar“ den
        Wert als Attribut ausweist. Er darf **nicht** eigenständig aus
        ``NEXT_DAY_PRICES_HOUR`` gebildet werden: Der Jitter verschiebt die
        Schwelle um bis zu ``FETCH_JITTER_MINUTES``, und in dieser Spanne wäre
        ein leerer Morgen-Tag sonst fälschlich als überfällig ausgewiesen.
        """
        return dt_util.as_local(now).replace(
            hour=NEXT_DAY_PRICES_HOUR,
            minute=self._jitter_minutes(now),
            second=0,
            microsecond=0,
        )

    def _next_day_prices_due(self, now: datetime) -> bool:
        """Ob die Morgen-Preise laut API-Zeitplan bereits vorliegen sollten."""
        return dt_util.as_local(now) >= self.next_day_prices_expected_after(now)

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

    def _pruefe_grundgebuehr_einheit(self, bisherige_einheit: str | None) -> None:
        """Meldet, wenn die API die Einheit der Grundgebühr gewechselt hat.

        Die Anzeige-Einheit des Grundgebühr-Sensors ist fest hinterlegt;
        ``sensor.async_setup_entry`` gleicht sie beim Einrichten einmal gegen
        die der API ab. Nur einmal – wechselt die API sie im laufenden Betrieb,
        zeigte der Sensor bis zum nächsten Neustart stillschweigend eine
        falsche Einheit an. Home Assistant läuft bei vielen Nutzern wochenlang
        durch; das ist keine kurze Lücke.

        Gemeldet wird der **Wechsel**, nicht der Abgleich mit der
        Anzeige-Einheit: Beim Einrichten stimmten beide überein, jede spätere
        Änderung heißt also, dass sie es nicht mehr tun. Der Koordinator muss
        die Anzeige-Einheit dafür nicht kennen – er sieht ohnehin nur, was die
        API liefert.

        Läuft nur nach einem **erfolgreichen** Abruf und damit höchstens
        täglich; die minütliche Neuberechnung berührt sie nicht.

        Verglichen wird gegen die zuletzt *vorhandene* Einheit
        (``_letzte_grundgebuehr_einheit``) und nicht gegen die des vorigen
        Abrufs. Sonst risse eine Lücke die Kette: Entfiele die Grundgebühr
        vorübergehend und käme mit einer **anderen** Einheit zurück, wäre die
        Vergleichsgröße beim Wiederauftauchen ``None`` – der Wechsel bliebe
        unbemerkt, und der Sensor zeigte einen Jahreswert weiter als
        Monatswert. Genau der Fall, den diese Methode verhindern soll.

        ``bisherige_einheit`` (der Wert des vorigen Abrufs) wird trotzdem
        gebraucht, aber nur für den **Übergang** in den Entfall: Ohne ihn
        stünde die Entfall-Meldung bei jedem weiteren Abruf erneut im Log.
        """
        if self._last_result is None:
            return

        neue_einheit = self._last_result.basic_fee_unit

        if neue_einheit is None:
            # Nur den Übergang melden, nicht jeden Abruf danach. Die zuletzt
            # bekannte Einheit bleibt bewusst gemerkt – kommt die Grundgebühr
            # mit einer anderen zurück, ist das ein Wechsel.
            if bisherige_einheit is not None:
                _LOGGER.warning(
                    "Die smartENERGY-API liefert keine Grundgebühr mehr "
                    "(zuletzt in '%s'). Der zugehörige Sensor bleibt ohne "
                    "Wert, bis sie wieder erscheint.",
                    bisherige_einheit,
                )
            return

        zuletzt_gemeldet = self._letzte_grundgebuehr_einheit
        self._letzte_grundgebuehr_einheit = neue_einheit
        if zuletzt_gemeldet is None or neue_einheit == zuletzt_gemeldet:
            # Erster Abruf mit Grundgebühr – es gibt nichts zu vergleichen.
            return

        _LOGGER.warning(
            "Die smartENERGY-API meldet die Grundgebühr jetzt in '%s' statt in "
            "'%s'. Der Sensor führt weiterhin die beim Einrichten geprüfte "
            "Einheit – sein Wert passt damit möglicherweise nicht mehr.",
            neue_einheit,
            zuletzt_gemeldet,
        )

    async def _async_update_data(self) -> SmartTimesData:
        """Berechnet die Entitätsdaten neu und ruft bei Bedarf die API ab."""
        now = dt_util.now()

        if self._needs_fetch(now) and self._fetch_allowed(now):
            # Vor dem Überschreiben sichern: `_pruefe_grundgebuehr_einheit`
            # vergleicht die Einheit dieses Abrufs mit der des vorigen.
            bisherige_einheit = (
                self._last_result.basic_fee_unit
                if self._last_result is not None
                else None
            )
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
                # Frühere Daten behalten, falls ein einzelner Abruf
                # scheitert. `last_update_success` bleibt damit wahr und die
                # Entitäten bleiben *verfügbar*: Decken die gecachten Preise den
                # aktuellen Zeitpunkt nicht mehr ab, melden sie „unbekannt“
                # statt „nicht verfügbar“. Das ist gewollt – ein Preisplan
                # bleibt brauchbar, solange er reicht – und ab
                # FETCH_FAILURE_REPAIR_HOURS weist ein Repair-Issue darauf hin.
                _LOGGER.warning(
                    "Aktualisierung der smartENERGY-Preise fehlgeschlagen, "
                    "verwende zwischengespeicherte Daten (nächster Versuch in "
                    "%d Minuten): %s",
                    self._retry_delay() // timedelta(minutes=1),
                    err,
                )
            else:
                self._last_success = now
                self._pruefe_grundgebuehr_einheit(bisherige_einheit)
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
