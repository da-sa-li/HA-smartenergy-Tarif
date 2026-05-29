"""Netzentgelte (Netzebene 7, Viertelstundenmessung) für smartTIMES.

Die per-kWh-Netzentgelte hängen vom **Netzgebiet** ab und – über den
Sommer-Nieder-Arbeitspreis (SNAP) – von der **Uhrzeit/Jahreszeit**:

* Netznutzungsentgelt-Arbeitspreis: normaler ``AP`` bzw. reduzierter ``SNAP``
  im Sommer-Mittagsfenster.
* Netzverlustentgelt: konstant je Netzgebiet.

Annahmen (vom Anwendungsfall gedeckt): Haushaltskunden liegen auf Netzebene 7
und haben für den smartTIMES-Tarif ohnehin ein Smart Meter mit aktiver
Viertelstundenmessung (IME) – damit gilt der SNAP automatisch.

Der **Leistungspreis (LP)** ist ein Kapazitätsentgelt (€/kW nach Spitzenlast)
und lässt sich nicht sinnvoll in einen ct/kWh-Preis umrechnen; er wird hier
bewusst nicht berücksichtigt.

Alle Sätze sind **netto** in ct/kWh; die USt. wird – wie beim Arbeitspreis und
den Abgaben – erst am Ende auf die Summe angewendet (siehe Coordinator).
Werte: Stand 2026.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
class GridZone:
    """Netzentgelte eines Netzgebiets (NE 7, IME), netto in ct/kWh."""

    key: str
    name: str
    usage_ap: float  # Netznutzungsentgelt-Arbeitspreis (Regelzeiten)
    usage_snap: float  # Sommer-Nieder-Arbeitspreis (reduziert)
    loss: float  # Netzverlustentgelt

    def usage_rate(self, moment: datetime) -> float:
        """Gültiger Netznutzungs-Arbeitspreis (AP bzw. SNAP) zu ``moment``."""
        return self.usage_snap if is_snap(moment) else self.usage_ap

    def breakdown(self, moment: datetime) -> dict[str, float]:
        """Netto-Sätze (ct/kWh) je Netzentgelt-Position."""
        return {
            "grid_usage": self.usage_rate(moment),
            "grid_loss": self.loss,
        }

    def total_ct_per_kwh(self, moment: datetime) -> float:
        """Summe der per-kWh-Netzentgelte (netto, ct/kWh) zu ``moment``."""
        return self.usage_rate(moment) + self.loss


# Netzentgelte 2026, Netzebene 7, mit Viertelstundenmessung. Netto in ct/kWh.
# Reihenfolge: usage_ap, usage_snap, loss.
GRID_ZONES: Final[dict[str, GridZone]] = {
    "burgenland": GridZone("burgenland", "Burgenland", 5.83, 4.66, 0.000),
    "kaernten": GridZone("kaernten", "Kärnten", 5.47, 4.38, 0.368),
    "klagenfurt": GridZone("klagenfurt", "Klagenfurt", 4.36, 3.49, 0.578),
    "niederoesterreich": GridZone(
        "niederoesterreich", "Niederösterreich", 6.65, 5.32, 0.384
    ),
    "oberoesterreich": GridZone(
        "oberoesterreich", "Oberösterreich", 4.68, 3.74, 0.528
    ),
    "linz": GridZone("linz", "Linz", 3.26, 2.61, 0.487),
    "salzburg": GridZone("salzburg", "Salzburg", 3.91, 3.13, 0.357),
    "steiermark": GridZone("steiermark", "Steiermark", 6.78, 5.42, 0.336),
    "graz": GridZone("graz", "Graz", 4.23, 3.38, 0.658),
    "tirol": GridZone("tirol", "Tirol", 3.66, 2.93, 0.293),
    "innsbruck": GridZone("innsbruck", "Innsbruck", 5.72, 4.58, 0.453),
    "vorarlberg": GridZone("vorarlberg", "Vorarlberg", 2.84, 2.27, 0.393),
    "wien": GridZone("wien", "Wien", 4.21, 3.37, 0.700),
    "kleinwalsertal": GridZone("kleinwalsertal", "Kleinwalsertal", 11.40, 9.12, 0.401),
}


def get_zone(key: str | None) -> GridZone | None:
    """Liefert das Netzgebiet zum Schlüssel (oder ``None``, falls keins gewählt)."""
    if not key:
        return None
    return GRID_ZONES.get(key)
