"""Netzentgelte (Netzebene 7, Viertelstundenmessung) für smartTIMES.

Die per-kWh-Netzentgelte hängen vom **Netzgebiet** ab und – über den
Sommer-Nieder-Arbeitspreis (SNAP) – von der **Uhrzeit/Jahreszeit**:

* Netznutzungsentgelt-Arbeitspreis: normaler ``AP`` bzw. reduzierter ``SNAP``
  im Sommer-Mittagsfenster.
* Netzverlustentgelt: konstant je Netzgebiet.

Die Sätze eines Netzgebiets sind als **datierte Satzgruppen** (`GridRates` mit
``since``/``until``) hinterlegt – dieselbe Mechanik wie in ``surcharges.py``. Ein
Wechsel unter dem Jahr (z. B. der Übergang auf das neue Entgeltsystem der
Netzebene 7, der je Netzgebiet zu einem anderen Tag greifen kann) braucht damit
kein Release zum Stichtag: Die neue Gruppe steht in der Tabelle und greift am
``since``-Tag von selbst.

Annahmen (vom Anwendungsfall gedeckt): Haushaltskunden liegen auf Netzebene 7
und haben für den smartTIMES-Tarif ohnehin ein Smart Meter mit aktiver
Viertelstundenmessung (IME) – damit gilt der SNAP automatisch.

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
from datetime import date, datetime
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


@dataclass(frozen=True)
class GridRates:
    """Netzentgelte eines Netzgebiets für einen Zeitraum, netto in ct/kWh.

    ``since``/``until`` sind jeweils inklusive; ``None`` bedeutet „unbegrenzt“.
    """

    usage_ap: float  # Netznutzungsentgelt-Arbeitspreis (Regelzeiten)
    usage_snap: float  # Sommer-Nieder-Arbeitspreis (reduziert)
    loss: float  # Netzverlustentgelt
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
        die zeitlich nächstliegende – vor der ersten diese, sonst die letzte.
        Dass es im Datenjahr keine Lücken gibt, sichert ein Test.
        """
        for group in self.rates:
            if group.applies_on(day):
                return group
        first = self.rates[0]
        if first.since is not None and day < first.since:
            return first
        return self.rates[-1]

    def _rates_at(self, moment: datetime) -> GridRates:
        """Satzgruppe zum lokalen Kalendertag von ``moment``."""
        return self.rates_on(dt_util.as_local(moment).date())

    def usage_rate(self, moment: datetime) -> float:
        """Gültiger Netznutzungs-Arbeitspreis (AP bzw. SNAP) zu ``moment``."""
        group = self._rates_at(moment)
        return group.usage_snap if is_snap(moment) else group.usage_ap

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
# Reihenfolge je Satzgruppe: usage_ap, usage_snap, loss (+ optional since/until).
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
