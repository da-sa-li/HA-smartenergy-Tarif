"""Tests der Last-Glättung (deterministischer Jitter).

Geprüft werden **Invarianten**, die unabhängig vom konkreten Phasenwert gelten –
nicht ein nachgerechneter Hash. Das hält die Tests gegen Implementierungsdetails
robust und prüft trotzdem die zugesagten Eigenschaften.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custom_components.smartenergy import jitter
from tests.conftest import VIENNA

START = datetime(2026, 6, 5, 10, 0, tzinfo=VIENNA)
END = datetime(2026, 6, 5, 14, 0, tzinfo=VIENNA)  # 4-Stunden-Block


def test_phase_is_deterministic():
    """Dieselbe Subentry-ID ergibt immer denselben Phasenwert."""
    assert jitter.cheap_phase("subentry-123") == jitter.cheap_phase("subentry-123")


def test_phase_differs_by_seed():
    """Unterschiedliche IDs ergeben unterschiedliche Phasen."""
    assert jitter.cheap_phase("boiler") != jitter.cheap_phase("wallbox")


@pytest.mark.parametrize("seed", ["", "x", "boiler", "wallbox", "0" * 40])
def test_phase_in_unit_interval(seed):
    """Der Phasenwert liegt stets im Intervall [0, 1)."""
    assert 0.0 <= jitter.cheap_phase(seed) < 1.0


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_normal_window_invariants(phase):
    """Normales Blockende: nie vor Start, feste Fensterlänge (L - 300 s)."""
    on, off = jitter.jittered_window(START, END, phase, soft_end=False)
    # Nie vor Blockbeginn einschalten; Einschaltversatz max. 600 s.
    assert on >= START
    assert on <= START + timedelta(seconds=600)
    # Fensterlänge ist konstant, unabhängig von der Phase.
    assert (off - on) == (END - START) - timedelta(seconds=300)


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_soft_end_window_invariants(phase):
    """soft_end: Ausschalten nie über das Blockende hinaus, Länge (L - 600 s)."""
    on, off = jitter.jittered_window(START, END, phase, soft_end=True)
    assert on >= START
    assert off <= END
    assert (off - on) == (END - START) - timedelta(seconds=600)


@pytest.mark.parametrize("soft_end", [False, True])
@pytest.mark.parametrize("phase", [0.0, 0.3, 0.5, 0.99])
@pytest.mark.parametrize("seconds", [240, 300, 400, 900])
def test_short_block_never_yields_empty_window(seconds, phase, soft_end):
    """Ein Block, den der Jitter aufzehren würde, wird ungejittert geschaltet.

    Die feste Verkürzung beträgt 300 s (normales Blockende) bzw. 600 s
    (``soft_end``). Ist der Block nicht länger als das, fiele das Fenster auf
    einen Punkt zusammen: ``on <= moment < off`` träfe nie zu und der Sensor
    bliebe dauerhaft „aus". Die gewählten Längen decken beide Regime ab – 400 s
    ist z. B. nur für ``soft_end`` zu kurz, 900 s (ein Viertelstunden-Intervall,
    das Raster der API) für keines von beiden.
    """
    end = START + timedelta(seconds=seconds)
    on, off = jitter.jittered_window(START, end, phase, soft_end=soft_end)
    # Das Fenster ist nie leer – der Sensor schaltet also überhaupt ein.
    assert off > on
    # Und die zugesagten Flankengrenzen gelten weiterhin.
    assert on >= START
    if soft_end:
        assert off <= end


# --- Schaltfenster über die Tagesgrenze -------------------------------------- #
#
# Die *Auswahl* der günstigen Intervalle erfolgt je Kalendertag. Ein über
# Mitternacht durchgehend günstiger Zeitraum darf dadurch aber nicht in zwei
# getrennt gejitterte Blöcke zerfallen: Deren Fenster stoßen nicht mehr
# aneinander, sondern klaffen um JITTER_OFF_SPAN_SECONDS / 2 = 5 min auseinander
# (bei soft_end 10 min) – und zwar für jede Phase gleich weit, weil sich beide
# Flanken um denselben Betrag verschieben. Ohne Jitter gäbe es die Lücke nicht,
# beide Grenzen fallen exakt auf Mitternacht.
#
# Datengrundlage: Die smartTIMES-Fixture hat je Tag drei Preisstufen zu je 32
# Viertelstunden, an beiden Tagen identisch verteilt:
#   11,316 -> Stunden 02,03,10-15
#   13,02  -> Stunden 00,01,04,05,09,16,22,23
#   15,852 -> Stunden 06-08,17-21
# Bei 9 h (= 36 Intervalle) reicht die Auswahl über die 32 Intervalle der
# günstigsten Stufe hinaus in die Stufe 13,02 hinein, die bei Gleichstand
# vollständig mitgenommen wird. Ausgewählt sind damit je Tag die Stunden 00-05,
# 09-16 und 22-23. Der letzte Block des 05.06. (22:00-24:00) grenzt also exakt
# an den ersten des 06.06. (00:00-06:00).

DAY_5 = date(2026, 6, 5)
DAY_6 = date(2026, 6, 6)
CHEAP_HOURS = 9.0
# Fester Phasenwert: Die geprüften Eigenschaften gelten für jede Phase, ein
# nachgerechneter Hash wäre hier nur Implementierungsdetail.
PHASE = 0.25


@pytest.fixture(name="two_day_data")
def _two_day_data(make_data, smarttimes_payload):
    """``SmartTimesData`` über die zwei Tage der smartTIMES-Fixture."""
    return make_data(smarttimes_payload, include_vat=True, grid_zone=None)


def test_blocks_merge_across_midnight(two_day_data):
    """Der über Mitternacht durchgehende Zeitraum ist ein einziger Block."""
    # Erwartet: 05.06. 22:00 -> 06.06. 06:00 (Herleitung siehe oben).
    start, end, _ = two_day_data._cheap_blocks_spanning(DAY_5, CHEAP_HOURS)[-1]
    assert start == datetime(2026, 6, 5, 22, 0, tzinfo=VIENNA)
    assert end == datetime(2026, 6, 6, 6, 0, tzinfo=VIENNA)


def test_merged_block_looks_the_same_from_both_days(two_day_data):
    """Die Zusammenfassung ist symmetrisch – beide Tage liefern denselben Block.

    Nur dann ist es gleichgültig, über welchen Tag ein Aufrufer den Block
    findet: ``is_cheap_now`` prüft Vortag + Tag, ``next_cheap_on`` Tag +
    Folgetag.
    """
    assert (
        two_day_data._cheap_blocks_spanning(DAY_5, CHEAP_HOURS)[-1]
        == two_day_data._cheap_blocks_spanning(DAY_6, CHEAP_HOURS)[0]
    )


def test_selection_itself_stays_per_day(two_day_data):
    """Die tageweise Auswahl selbst bleibt unberührt.

    Zusammengefasst wird ausschließlich für den Jitter; welche Intervalle als
    günstig gelten, ändert sich dadurch nicht.
    """
    # Je Tag unverändert die Stunden 00-05, 09-16 und 22-23 (siehe oben).
    for day in (DAY_5, DAY_6):
        blocks = two_day_data._cheap_blocks(day, CHEAP_HOURS)
        assert [(s.hour, e.hour) for s, e, _ in blocks] == [(0, 6), (9, 17), (22, 0)]


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_no_switch_off_gap_at_midnight(two_day_data, phase):
    """Der Sensor schaltet am Tageswechsel nicht kurz ab – für jede Phase."""
    moment = datetime(2026, 6, 5, 23, 30, tzinfo=VIENNA)
    last = datetime(2026, 6, 6, 0, 30, tzinfo=VIENNA)
    while moment <= last:
        assert two_day_data.is_cheap_now(moment, CHEAP_HOURS, phase), moment
        moment += timedelta(minutes=1)


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_next_cheap_start_has_no_phantom_midnight_restart(two_day_data, phase):
    """Mitten im Block wird kein Neustart um Mitternacht gemeldet.

    Getrennte Blöcke ließen ``next_cheap_on`` um 23:30 auf den 06.06. 00:00
    zeigen, obwohl der Verbraucher längst läuft. Richtig ist der nächste
    *echte* Block, also der 06.06. 09:00 (gejittert innerhalb der Stunde 09).
    """
    next_on = two_day_data.next_cheap_on(
        datetime(2026, 6, 5, 23, 30, tzinfo=VIENNA), CHEAP_HOURS, phase
    )
    assert next_on is not None
    assert next_on.date() == DAY_6
    assert next_on.hour == 9
