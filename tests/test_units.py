"""Tests der Einheiten-Umrechnung ct/kWh -> EUR/kWh.

Die Sollwerte sind von Hand gebildet (Division durch 100), nicht aus der
Funktion erzeugt.
"""

from __future__ import annotations

import pytest

from custom_components.smartenergy.const import to_eur


@pytest.mark.parametrize(
    ("ct", "eur"),
    [
        # Die drei Preisstufen des 05.06.2026 aus tests/fixtures/smarttimes.json.
        (11.316, 0.11316),
        (13.02, 0.1302),
        (15.852, 0.15852),
        # Gesamtpreis Wien, 14:00 (vgl. tests/test_coordinator_math.py).
        (19.716, 0.19716),
        # Nebenkosten-Sätze aus surcharges.py (netto, Stand 2026).
        (0.1, 0.001),
        (0.62, 0.0062),
        (0.0, 0.0),
    ],
)
def test_umrechnung(ct: float, eur: float):
    """ct/kWh geteilt durch 100 ergibt EUR/kWh."""
    assert to_eur(ct) == pytest.approx(eur)


def test_none_bleibt_none():
    """Fehlt ein Preis, bleibt er auch nach der Umrechnung unbekannt."""
    assert to_eur(None) is None


def test_vier_ct_stellen_bleiben_erhalten():
    """Die 4-Stellen-Rundung des Coordinators überlebt die Umrechnung.

    `coordinator.py` rundet Preise auf 4 Nachkommastellen in ct. Das sind genau
    6 Stellen in EUR – mit weniger ginge die letzte Stelle verloren.
    """
    # 19,7161 ct -> 0,197161 EUR (nicht 0,19716).
    assert to_eur(19.7161) == 0.197161
    # Kleinster in ct darstellbarer Betrag.
    assert to_eur(0.0001) == 0.000001
