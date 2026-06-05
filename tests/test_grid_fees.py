"""Tests der Netzentgelte: SNAP-Fenster, Zonen-Lookup, Summen.

Werte für Wien (Stand 2026, netto): usage_ap=6,98 · usage_snap=5,58 · loss=0,700.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.smartenergy import grid_fees
from tests.conftest import VIENNA


def _dt(year, month, day, hour, minute=0):
    """Zeitzonenbehaftetes datetime in Europe/Vienna (knappe Test-Schreibweise)."""
    return datetime(year, month, day, hour, minute, tzinfo=VIENNA)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (_dt(2026, 6, 5, 10, 0), True),    # Start 10:00 inklusive
        (_dt(2026, 6, 5, 15, 59), True),   # kurz vor Ende
        (_dt(2026, 6, 5, 16, 0), False),   # Ende 16:00 exklusiv
        (_dt(2026, 6, 5, 9, 59), False),   # vor dem Fenster
        (_dt(2026, 4, 1, 12, 0), True),    # April: Sommerhalbjahr beginnt
        (_dt(2026, 9, 30, 12, 0), True),   # September: noch drin
        (_dt(2026, 10, 1, 12, 0), False),  # Oktober: raus
        (_dt(2026, 1, 15, 12, 0), False),  # Winter
    ],
)
def test_is_snap(moment, expected):
    """Das SNAP-Fenster gilt im Sommerhalbjahr 10:00-16:00 (Ende exklusiv)."""
    assert grid_fees.is_snap(moment) is expected


def test_zone_lookup():
    """Der Zonen-Lookup liefert None für leere/unbekannte Schlüssel, sonst die Zone."""
    assert grid_fees.get_zone(None) is None
    assert grid_fees.get_zone("") is None
    assert grid_fees.get_zone("none") is None        # kein Eintrag mit diesem Schlüssel
    assert grid_fees.get_zone("unbekannt") is None
    assert grid_fees.get_zone("wien").name == "Wien"


def test_usage_rate_snap_vs_normal():
    """Der Netznutzungs-Arbeitspreis ist im SNAP-Fenster reduziert, sonst normal."""
    zone = grid_fees.get_zone("wien")
    assert zone.usage_rate(_dt(2026, 6, 5, 14)) == 5.58   # SNAP
    assert zone.usage_rate(_dt(2026, 1, 15, 12)) == 6.98  # Regelzeit


def test_total_non_snap():
    """Außerhalb des SNAP: 6,98 + 0,700 = 7,68 ct/kWh netto."""
    zone = grid_fees.get_zone("wien")
    assert zone.total_ct_per_kwh(_dt(2026, 1, 15, 12)) == pytest.approx(7.68)


def test_total_snap():
    """Im SNAP-Fenster: 5,58 + 0,700 = 6,28 ct/kWh netto."""
    zone = grid_fees.get_zone("wien")
    assert zone.total_ct_per_kwh(_dt(2026, 6, 5, 14)) == pytest.approx(6.28)


def test_breakdown_uses_snap_rate():
    """Die Aufschlüsselung nutzt je nach Zeitpunkt den SNAP- bzw. Regelsatz."""
    zone = grid_fees.get_zone("wien")
    assert zone.breakdown(_dt(2026, 6, 5, 14)) == {"grid_usage": 5.58, "grid_loss": 0.700}
    assert zone.breakdown(_dt(2026, 1, 15, 12)) == {"grid_usage": 6.98, "grid_loss": 0.700}
