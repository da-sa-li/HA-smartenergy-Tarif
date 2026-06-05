"""Tests der Last-Glättung (deterministischer Jitter).

Geprüft werden **Invarianten**, die unabhängig vom konkreten Phasenwert gelten –
nicht ein nachgerechneter Hash. Das hält die Tests gegen Implementierungsdetails
robust und prüft trotzdem die zugesagten Eigenschaften.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.smartenergy import jitter
from tests.conftest import VIENNA

START = datetime(2026, 6, 5, 10, 0, tzinfo=VIENNA)
END = datetime(2026, 6, 5, 14, 0, tzinfo=VIENNA)  # 4-Stunden-Block


def test_phase_is_deterministic():
    assert jitter.cheap_phase("subentry-123") == jitter.cheap_phase("subentry-123")


def test_phase_differs_by_seed():
    assert jitter.cheap_phase("boiler") != jitter.cheap_phase("wallbox")


@pytest.mark.parametrize("seed", ["", "x", "boiler", "wallbox", "0" * 40])
def test_phase_in_unit_interval(seed):
    assert 0.0 <= jitter.cheap_phase(seed) < 1.0


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_normal_window_invariants(phase):
    on, off = jitter.jittered_window(START, END, phase, soft_end=False)
    # Nie vor Blockbeginn einschalten; Einschaltversatz max. 600 s.
    assert on >= START
    assert on <= START + timedelta(seconds=600)
    # Fensterlänge ist konstant (L - 300 s), unabhängig von der Phase.
    assert (off - on) == (END - START) - timedelta(seconds=300)


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_soft_end_window_invariants(phase):
    on, off = jitter.jittered_window(START, END, phase, soft_end=True)
    assert on >= START
    # soft_end: das Ausschalten greift nie über das Blockende hinaus.
    assert off <= END
    # Fensterlänge konstant (L - 600 s).
    assert (off - on) == (END - START) - timedelta(seconds=600)
