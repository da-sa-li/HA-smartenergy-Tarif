"""Netzentgelte (Netzebene 7, Viertelstundenmessung) für smartTIMES.

Die per-kWh-Netzentgelte hängen vom **Netzgebiet** ab und – über den
Sommer-Nieder-Arbeitspreis (SNAP) und den Winter-Nieder-Arbeitspreis (WiNAP) –
von der **Uhrzeit/Jahreszeit**:

* Netznutzungsentgelt-Arbeitspreis: normaler ``AP``, reduzierter ``SNAP`` im
  Sommer-Mittagsfenster bzw. ``WiNAP`` in den Winternächten (erstmals ab
  1. Oktober 2027).
* Netzverlustentgelt: konstant je Netzgebiet.

Die Sätze eines Netzgebiets sind als **datierte Satzgruppen** (`GridRates` mit
``since``/``until``) hinterlegt – dieselbe Mechanik wie in ``surcharges.py``. Ein
Wechsel unter dem Jahr (z. B. der Übergang auf das neue Entgeltsystem der
Netzebene 7, der je Netzgebiet zu einem anderen Tag greifen kann) braucht damit
kein Release zum Stichtag: Die neue Gruppe steht in der Tabelle und greift am
``since``-Tag von selbst.

Annahmen (vom Anwendungsfall gedeckt): Haushaltskunden liegen auf Netzebene 7
und haben für den smartTIMES-Tarif ohnehin ein Smart Meter mit aktiver
Viertelstundenmessung (IME) – damit gelten SNAP und WiNAP automatisch. Die
Grundlage ist § 7 Abs. 5 SNE-G-V: Beide gelten nur mit gemessenen
Viertelstundenwerten.

Zugrunde gelegt wird die Tarifvariante **ohne Leistungsmessung** ("nicht
gemessene Leistung"): Haushaltskunden ohne Lastprofilzähler zahlen einen reinen
Arbeitspreis ohne separaten Leistungspreis (€/kW nach Spitzenlast). Ein solcher
Leistungspreis ließe sich ohnehin nicht sinnvoll in einen ct/kWh-Preis umrechnen
und wird hier daher nicht berücksichtigt.

Alle Sätze sind **netto** in ct/kWh; die USt. wird – wie beim Arbeitspreis und
den Abgaben – erst am Ende auf die Summe angewendet (siehe Coordinator).
Werte: Stand 2026 (siehe `const.TARIFF_DATA_YEAR` – bei der jährlichen
Aktualisierung der Sätze auch dort das Jahr anheben, sonst meldet
`repairs.py` ein Repair-Issue).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

from homeassistant.util import dt as dt_util

# SNAP-Fenster: 1. April – 30. September, täglich 10:00–16:00 Uhr (lokale Zeit),
# inkl. Wochenende. Maßgeblich ist der Beginn des jeweiligen 15-Minuten-Intervalls.
SNAP_MONTHS: Final = range(4, 10)  # April (4) bis einschließlich September (9)
SNAP_START_HOUR: Final = 10
SNAP_END_HOUR: Final = 16


def is_snap(moment: datetime) -> bool:
    """Ob der Sommer-Nieder-Arbeitspreis zu ``moment`` gilt."""
    local = dt_util.as_local(moment)
    return local.month in SNAP_MONTHS and SNAP_START_HOUR <= local.hour < SNAP_END_HOUR


# WiNAP: 1. Oktober – 31. März, je 23:00 bis 05:00 Uhr des Folgetags (lokale
# Zeit; § 7 Abs. 4 SNE-G-V). Die Nacht zählt zu dem Tag, an dem sie beginnt:
# 01.10.2027 02:00 gehört zur Nacht des 30.09. und liegt außerhalb, 01.04.2028
# 04:45 noch zur Nacht des 31.03. und liegt innerhalb. Erstmals gilt der WiNAP
# in der Nacht ab 01.10.2027 (§ 32 Abs. 4 SNE-G-V). Maßgeblich ist wie beim SNAP
# der Beginn des jeweiligen 15-Minuten-Intervalls.
WINAP_FIRST_NIGHT: Final = date(2027, 10, 1)
WINAP_MONTHS: Final = (10, 11, 12, 1, 2, 3)
WINAP_START_HOUR: Final = 23
WINAP_END_HOUR: Final = 5


def is_winap(moment: datetime) -> bool:
    """Ob der Winter-Nieder-Arbeitspreis zu ``moment`` gilt.

    Über die *lokale* Stunde bestimmt, damit das Fenster an den Umstellungstagen
    der Sommerzeit nach Wanduhr gilt (wie ``is_snap``). Eine Prüfung über den
    Monat des Zeitpunkts allein läge an beiden Rändern um fünf Stunden daneben.
    """
    local = dt_util.as_local(moment)
    if local.hour >= WINAP_START_HOUR:
        night = local.date()
    elif local.hour < WINAP_END_HOUR:
        night = local.date() - timedelta(days=1)
    else:
        return False
    return night >= WINAP_FIRST_NIGHT and night.month in WINAP_MONTHS


@dataclass(frozen=True)
class GridRates:
    """Netzentgelte eines Netzgebiets für einen Zeitraum, netto in ct/kWh.

    ``since``/``until`` sind jeweils inklusive; ``None`` bedeutet „unbegrenzt“.
    """

    usage_ap: float  # Netznutzungsentgelt-Arbeitspreis (Regelzeiten)
    usage_snap: float  # Sommer-Nieder-Arbeitspreis (reduziert)
    loss: float  # Netzverlustentgelt
    # Winter-Nieder-Arbeitspreis. Die Verordnung nennt keine Höhe (und keinen
    # Prozentsatz), er wird deshalb ausdrücklich hinterlegt und nicht aus
    # ``usage_ap`` abgeleitet. Die Sätze gibt es erst mit der SNE-T-V 2027; bis
    # dahin ``None`` – dann gilt auch im WiNAP-Fenster der normale Arbeitspreis.
    usage_winap: float | None = None
    since: date | None = None
    until: date | None = None

    def applies_on(self, day: date) -> bool:
        """Ob die Satzgruppe an einem bestimmten Kalendertag gilt."""
        if self.since is not None and day < self.since:
            return False
        return self.until is None or day <= self.until


@dataclass(frozen=True)
class GridZone:
    """Netzentgelte eines Netzgebiets (NE 7, IME) als datierte Satzgruppen.

    ``rates`` ist chronologisch sortiert und überschneidungsfrei; es gilt die
    **erste** passende Gruppe nach dem lokalen Kalendertag des Intervalls.
    """

    key: str
    name: str
    rates: tuple[GridRates, ...]

    def __post_init__(self) -> None:
        """Verlangt mindestens eine Satzgruppe."""
        if not self.rates:
            raise ValueError(f"Netzgebiet {self.key}: keine Satzgruppe hinterlegt")

    def rates_on(self, day: date) -> GridRates:
        """Gültige Satzgruppe am ``day``.

        Anders als bei den Abgaben (``Surcharge.rate_on`` liefert 0) darf eine
        Lücke nie still zu „ohne Netzentgelt“ werden: Greift keine Gruppe, gilt
        die Gruppe mit dem kleinsten Abstand zu den inklusiven Grenzen. Vor der
        ersten gilt diese, nach der letzten jene; in einer inneren Lücke gilt die
        nähere der beiden angrenzenden Gruppen, bei Gleichstand die frühere.
        Dass es im Datenjahr keine Lücken gibt, sichert ein Test.
        """
        for group in self.rates:
            if group.applies_on(day):
                return group
        first = self.rates[0]
        if first.since is not None and day < first.since:
            return first
        for previous, following in zip(self.rates, self.rates[1:], strict=False):
            if (
                previous.until is not None
                and following.since is not None
                and previous.until < day < following.since
            ):
                if day - previous.until <= following.since - day:
                    return previous
                return following
        return self.rates[-1]

    def _rates_at(self, moment: datetime) -> GridRates:
        """Satzgruppe zum lokalen Kalendertag von ``moment``."""
        return self.rates_on(dt_util.as_local(moment).date())

    def usage_rate(self, moment: datetime) -> float:
        """Gültiger Netznutzungs-Arbeitspreis (AP, SNAP bzw. WiNAP) zu ``moment``.

        SNAP (Sommer, Mittag) und WiNAP (Winter, Nacht) überschneiden sich nie,
        eine Rangfolge ist deshalb nicht nötig.
        """
        group = self._rates_at(moment)
        if is_snap(moment):
            return group.usage_snap
        if group.usage_winap is not None and is_winap(moment):
            return group.usage_winap
        return group.usage_ap

    def breakdown(self, moment: datetime) -> dict[str, float]:
        """Netto-Sätze (ct/kWh) je Netzentgelt-Position."""
        return {
            "grid_usage": self.usage_rate(moment),
            "grid_loss": self._rates_at(moment).loss,
        }

    def total_ct_per_kwh(self, moment: datetime) -> float:
        """Summe der per-kWh-Netzentgelte (netto, ct/kWh) zu ``moment``."""
        return self.usage_rate(moment) + self._rates_at(moment).loss


# Netzentgelte 2026, Netzebene 7, Viertelstundenmessung (IME), Tarifvariante
# ohne Leistungsmessung ("nicht gemessene Leistung"). Netto in ct/kWh.
# Reihenfolge je Satzgruppe: usage_ap, usage_snap, loss (+ optional usage_winap,
# since/until; usage_winap folgt mit der SNE-T-V 2027).
GRID_ZONES: Final[dict[str, GridZone]] = {
    "burgenland": GridZone(
        "burgenland",
        "Burgenland",
        (GridRates(8.46, 6.77, 0.000),),
    ),
    "kaernten": GridZone(
        "kaernten",
        "Kärnten",
        (GridRates(9.67, 7.74, 0.368),),
    ),
    "klagenfurt": GridZone(
        "klagenfurt",
        "Klagenfurt",
        (GridRates(6.90, 5.52, 0.578),),
    ),
    "niederoesterreich": GridZone(
        "niederoesterreich",
        "Niederösterreich",
        (GridRates(8.79, 7.03, 0.384),),
    ),
    "oberoesterreich": GridZone(
        "oberoesterreich",
        "Oberösterreich",
        (GridRates(6.29, 5.03, 0.528),),
    ),
    "linz": GridZone(
        "linz",
        "Linz",
        (GridRates(5.57, 4.46, 0.487),),
    ),
    "salzburg": GridZone(
        "salzburg",
        "Salzburg",
        (GridRates(6.59, 5.27, 0.357),),
    ),
    "steiermark": GridZone(
        "steiermark",
        "Steiermark",
        (GridRates(8.82, 7.06, 0.336),),
    ),
    "graz": GridZone(
        "graz",
        "Graz",
        (GridRates(5.17, 4.14, 0.658),),
    ),
    "tirol": GridZone(
        "tirol",
        "Tirol",
        (GridRates(6.81, 5.45, 0.293),),
    ),
    "innsbruck": GridZone(
        "innsbruck",
        "Innsbruck",
        (GridRates(8.03, 6.42, 0.453),),
    ),
    "vorarlberg": GridZone(
        "vorarlberg",
        "Vorarlberg",
        (GridRates(4.96, 3.97, 0.393),),
    ),
    "wien": GridZone(
        "wien",
        "Wien",
        (GridRates(6.98, 5.58, 0.700),),
    ),
    "kleinwalsertal": GridZone(
        "kleinwalsertal",
        "Kleinwalsertal",
        (GridRates(17.73, 14.18, 0.401),),
    ),
}


def get_zone(key: str | None) -> GridZone | None:
    """Liefert das Netzgebiet zum Schlüssel (oder ``None``, falls keins gewählt)."""
    if not key:
        return None
    return GRID_ZONES.get(key)
