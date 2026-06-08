"""Nebenkosten (Steuern, Abgaben, künftig Netzentgelte) für smartTIMES.

Ein großer Teil des österreichischen Strompreises besteht nicht aus dem
Arbeitspreis, sondern aus Steuern/Abgaben und Netzentgelten. Diese Positionen
sind über Zeiträume hinweg gültig und ändern sich gelegentlich (z. B. die
befristete Senkung der Elektrizitätsabgabe bis Ende 2026).

Statt das mit verstreuter Datumslogik (``if heute > X``) abzubilden, werden die
Sätze hier **deklarativ** als datierte Tabelle hinterlegt: jeder Eintrag kennt
seinen Gültigkeitszeitraum. Dadurch greift z. B. ab dem 01.01.2027 automatisch
wieder der Regelsatz – ganz ohne Code-Änderung. Neue Positionen sind eine Zeile
mehr.

Alle Sätze sind **netto** in ct/kWh angegeben; die Umsatzsteuer wird – wie beim
Arbeitspreis – erst am Ende auf die Summe angewendet (siehe Coordinator).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final


@dataclass(frozen=True)
class DatedRate:
    """Ein ab/bis-datierter Satz (netto, in ct/kWh).

    ``since``/``until`` sind jeweils inklusive; ``None`` bedeutet „unbegrenzt“.
    """

    rate: float
    since: date | None = None
    until: date | None = None

    def applies_on(self, day: date) -> bool:
        """Ob der Satz an einem bestimmten Kalendertag gilt."""
        if self.since is not None and day < self.since:
            return False
        if self.until is not None and day > self.until:
            return False
        return True


@dataclass(frozen=True)
class Surcharge:
    """Eine benannte Nebenkostenposition mit zeitlich datierten Sätzen.

    Es gilt der **erste** passende Satz aus ``rates`` – die Einträge sollten
    daher überschneidungsfrei und vom spezifischsten zum allgemeinsten sortiert
    sein.
    """

    key: str
    name: str
    rates: tuple[DatedRate, ...]

    def rate_on(self, day: date) -> float:
        """Gültiger Satz (netto, ct/kWh) am ``day`` – 0, falls keiner greift."""
        for rate in self.rates:
            if rate.applies_on(day):
                return rate.rate
        return 0.0


# --- Konkrete Positionen -------------------------------------------------- #

# Elektrizitätsabgabe – bundeseinheitlich, also für ganz Österreich gleich.
# Regelsatz: 0,015 €/kWh = 1,5 ct/kWh.
# Befristet bis 31.12.2026 auf 0,001 €/kWh = 0,1 ct/kWh gesenkt. Die dafür nötigen
# Voraussetzungen werden hier als gegeben angenommen.
ELECTRICITY_TAX: Final = Surcharge(
    key="electricity_tax",
    name="Elektrizitätsabgabe",
    rates=(
        DatedRate(rate=0.1, until=date(2026, 12, 31)),
        DatedRate(rate=1.5, since=date(2027, 1, 1)),
    ),
)

# Erneuerbaren-Förderbeitrag (vormals Ökostromförderbeitrag), bundeseinheitlich
# je Netzebene festgelegt. Netzebene 7, ohne Leistungsmessung ("nicht gemessene
# Leistung"): 0,62 ct/kWh laut Erneuerbaren-Förderbeitragsverordnung 2026
# (BGBl. II Nr. 301/2025).
# 2022–2024 ausgesetzt, seit 01.01.2025 wieder aktiv. Hinterlegt ist nur der ab
# 2026 gültige Satz – die Integration bewertet ausschließlich Gegenwart/Zukunft,
# ein separater 2025-Satz ist daher nicht nötig.
# Hinweis: Wird jährlich neu festgelegt – Wert ist Stand 2026 und sollte zum
# Jahreswechsel zusammen mit `const.TARIFF_DATA_YEAR` aktualisiert werden,
# sonst meldet `repairs.py` ein Repair-Issue.
RENEWABLE_SUPPORT: Final = Surcharge(
    key="renewable_support",
    name="Erneuerbaren-Förderbeitrag",
    rates=(DatedRate(rate=0.62, since=date(2026, 1, 1)),),
)

# Alle bekannten Nebenkostenpositionen (bundeseinheitliche Abgaben). Die
# zonenabhängigen Netzentgelte stecken in ``grid_fees.py``.
SURCHARGES: Final[tuple[Surcharge, ...]] = (ELECTRICITY_TAX, RENEWABLE_SUPPORT)


def surcharge_breakdown(day: date) -> dict[str, float]:
    """Netto-Satz (ct/kWh) je Nebenkostenposition für einen Kalendertag."""
    return {surcharge.key: surcharge.rate_on(day) for surcharge in SURCHARGES}


def total_surcharge_ct_per_kwh(day: date) -> float:
    """Summe aller Nebenkosten (netto, ct/kWh) für einen Kalendertag."""
    return sum(surcharge.rate_on(day) for surcharge in SURCHARGES)
