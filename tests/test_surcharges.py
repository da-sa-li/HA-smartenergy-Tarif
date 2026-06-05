"""Tests der bundeseinheitlichen Abgaben (datierte Tabellenlogik).

Sollwerte aus der Spezifikation (README/CLAUDE.md):
* Elektrizitätsabgabe: 0,1 ct/kWh netto bis 31.12.2026, ab 01.01.2027 wieder 1,5.
* Erneuerbaren-Förderbeitrag: 0,62 ct/kWh netto seit 01.01.2026.
"""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.smartenergy import surcharges


def test_electricity_tax_reduced_until_end_of_2026():
    assert surcharges.ELECTRICITY_TAX.rate_on(date(2026, 6, 5)) == 0.1
    # Letzter Tag des gesenkten Satzes (until ist inklusive).
    assert surcharges.ELECTRICITY_TAX.rate_on(date(2026, 12, 31)) == 0.1


def test_electricity_tax_regular_from_2027():
    # Satzwechsel greift automatisch über die datierte Tabelle, ohne Code-Änderung.
    assert surcharges.ELECTRICITY_TAX.rate_on(date(2027, 1, 1)) == 1.5
    assert surcharges.ELECTRICITY_TAX.rate_on(date(2030, 7, 1)) == 1.5


def test_renewable_support_active_since_2026():
    assert surcharges.RENEWABLE_SUPPORT.rate_on(date(2026, 1, 1)) == 0.62
    assert surcharges.RENEWABLE_SUPPORT.rate_on(date(2026, 6, 5)) == 0.62


def test_renewable_support_zero_before_2026():
    # Vor dem hinterlegten Zeitraum gilt kein Satz -> 0.
    assert surcharges.RENEWABLE_SUPPORT.rate_on(date(2025, 12, 31)) == 0.0


def test_total_2026():
    # 0,1 + 0,62 = 0,72 ct/kWh netto.
    assert surcharges.total_surcharge_ct_per_kwh(date(2026, 6, 5)) == pytest.approx(0.72)


def test_total_2027():
    # 1,5 + 0,62 = 2,12 ct/kWh netto.
    assert surcharges.total_surcharge_ct_per_kwh(date(2027, 1, 1)) == pytest.approx(2.12)


def test_breakdown_keys_and_values():
    assert surcharges.surcharge_breakdown(date(2026, 6, 5)) == {
        "electricity_tax": 0.1,
        "renewable_support": 0.62,
    }
