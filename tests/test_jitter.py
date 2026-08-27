"""Tests der Last-Glättung (deterministischer Jitter).

Geprüft werden **Invarianten**, die unabhängig vom konkreten Phasenwert gelten –
nicht ein nachgerechneter Hash. Das hält die Tests gegen Implementierungsdetails
robust und prüft trotzdem die zugesagten Eigenschaften.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custom_components.smartenergy import jitter
from custom_components.smartenergy.const import JITTER_SPAN_SECONDS
from tests.conftest import VIENNA

START = datetime(2026, 6, 5, 10, 0, tzinfo=VIENNA)
END = datetime(2026, 6, 5, 14, 0, tzinfo=VIENNA)  # 4-Stunden-Block

# Aus der Konstanten abgeleitet, nicht als Literal hinterlegt: Sonst würden die
# Tests eine geänderte Jitter-Breite stillschweigend mitmachen, statt die
# zugesagten Eigenschaften weiterhin an ihr zu messen.
SPAN = timedelta(seconds=JITTER_SPAN_SECONDS)


def test_phase_ist_deterministisch():
    """Dieselbe Subentry-ID ergibt immer denselben Phasenwert."""
    assert jitter.cheap_phase("subentry-123") == jitter.cheap_phase("subentry-123")


def test_phase_unterscheidet_sich_je_seed():
    """Unterschiedliche IDs ergeben unterschiedliche Phasen."""
    assert jitter.cheap_phase("boiler") != jitter.cheap_phase("wallbox")


@pytest.mark.parametrize("seed", ["", "x", "boiler", "wallbox", "0" * 40])
def test_phase_liegt_im_einheitsintervall(seed):
    """Der Phasenwert liegt stets im Intervall [0, 1)."""
    assert 0.0 <= jitter.cheap_phase(seed) < 1.0


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_fenster_bleibt_im_guenstigen_block(phase):
    """Beide Flanken wandern nach innen – das Fenster verlässt den Block nie.

    Das ist die Gleichbehandlung der Flanken: Wie schon beim Einschalten nie
    *vor* den Blockbeginn geschaltet wird, wird auch nie *nach* dem Blockende
    ausgeschaltet. Der Verbraucher läuft damit zu keinem Zeitpunkt in einer
    teureren Preiszone.
    """
    on, off = jitter.jittered_window(START, END, phase)
    assert START <= on <= START + SPAN
    assert END - SPAN <= off <= END


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_fensterlaenge_ist_blocklaenge_minus_breite(phase):
    """Die Fensterlänge ist L - SPAN, unabhängig von der Phase."""
    on, off = jitter.jittered_window(START, END, phase)
    assert (off - on) == (END - START) - SPAN


def test_fensterlaenge_ist_fuer_jede_phase_gleich():
    """Alle Sensoren schalten gleich lang – unabhängig von ihrer Phase.

    Das ist die eigentliche Zusage des Jitters: Er *verschiebt* das Fenster,
    er verkürzt es nicht je nach Sensor unterschiedlich stark. Weil sich beide
    Flanken denselben Versatz teilen, folgt das aus einer einzigen Breite und
    kann nicht dadurch kippen, dass zwei getrennte Breiten auseinanderlaufen –
    dann hinge die Fensterlänge davon ab, welche Subentry-ID ein Sensor
    zufällig bekommen hat.
    """
    lengths = {
        jitter.jittered_window(START, END, phase)[1]
        - jitter.jittered_window(START, END, phase)[0]
        for phase in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.999)
    }
    assert len(lengths) == 1


def test_beide_flanken_streuen_ueber_die_volle_breite():
    """Die Last-Glättung bleibt trotz Innen-Verschiebung erhalten.

    Beide Flanken streuen weiterhin über die volle Breite SPAN – verschoben ist
    nur die *Lage* des Fensters, nicht die Streuung. Sonst würden die
    Verbraucher zwar nie zu teuer laufen, dafür aber wieder gemeinsam schalten.
    """
    phases = [i / 100 for i in range(100)]
    ons = [jitter.jittered_window(START, END, p)[0] for p in phases]
    offs = [jitter.jittered_window(START, END, p)[1] for p in phases]
    # Streubreite = SPAN abzüglich eines Rasterschritts (99/100 * SPAN). Beide
    # Seiten des Vergleichs runden unabhängig voneinander auf Mikrosekunden,
    # daher mit Toleranz statt auf Gleichheit – sonst hinge der Test doch wieder
    # am konkreten Wert von JITTER_SPAN_SECONDS.
    toleranz = timedelta(microseconds=1)
    assert abs((max(ons) - min(ons)) - SPAN * 0.99) <= toleranz
    assert abs((max(offs) - min(offs)) - SPAN * 0.99) <= toleranz


@pytest.mark.parametrize("phase", [0.0, 0.3, 0.5, 0.99])
@pytest.mark.parametrize(
    "length",
    [SPAN * 0.4, SPAN / 2, SPAN * 0.7, SPAN, timedelta(minutes=15)],
    ids=["0.4*span", "span/2", "0.7*span", "span", "viertelstunde"],
)
def test_kurzer_block_ergibt_nie_ein_leeres_fenster(length, phase):
    """Ein Block, den der Jitter aufzehren würde, wird ungejittert geschaltet.

    Die feste Verkürzung beträgt SPAN. Ist der Block nicht länger als das,
    fiele das Fenster auf einen Punkt zusammen: ``on <= moment < off`` träfe
    nie zu und der Sensor bliebe dauerhaft „aus“. Die Längen sind an SPAN
    geknüpft; alle bis einschließlich SPAN greifen auf das Sicherheitsnetz
    zurück, die Viertelstunde (das Raster der API und damit die kleinste real
    vorkommende Blocklänge) nicht.
    """
    end = START + length
    on, off = jitter.jittered_window(START, end, phase)
    # Das Fenster ist nie leer – der Sensor schaltet also überhaupt ein.
    assert off > on
    # Und die zugesagten Flankengrenzen gelten weiterhin.
    assert on >= START
    assert off <= end


# --- Schaltfenster über die Tagesgrenze -------------------------------------- #
#
# Die *Auswahl* der günstigen Intervalle erfolgt je Kalendertag. Ein über
# Mitternacht durchgehend günstiger Zeitraum darf dadurch aber nicht in zwei
# getrennt gejitterte Blöcke zerfallen: Deren Fenster stoßen nicht mehr
# aneinander, sondern klaffen um SPAN auseinander – und zwar für jede Phase
# gleich weit, weil sich beide Flanken um denselben Betrag verschieben. Ohne
# Jitter gäbe es die Lücke nicht, beide Grenzen fallen exakt auf Mitternacht.
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
# Die zusammenhängenden Blöcke dieses Szenarios entstehen erst durch die
# Gleichstands-Erweiterung. Sie ist seit der Umstellung der Vorgabe nicht
# mehr der Standard und wird hier deshalb ausdrücklich angefordert.
ERWEITERN = False
# Fester Phasenwert: Die geprüften Eigenschaften gelten für jede Phase, ein
# nachgerechneter Hash wäre hier nur Implementierungsdetail.
PHASE = 0.25


@pytest.fixture(name="two_day_data")
def _two_day_data(make_data, smarttimes_payload):
    """``SmartTimesData`` über die zwei Tage der smartTIMES-Fixture."""
    return make_data(smarttimes_payload, include_vat=True, grid_zone=None)


def test_bloecke_verschmelzen_ueber_mitternacht(two_day_data):
    """Der über Mitternacht durchgehende Zeitraum ist ein einziger Block."""
    # Erwartet: 05.06. 22:00 -> 06.06. 06:00 (Herleitung siehe oben).
    start, end, _ = two_day_data._cheap_blocks_spanning(
        DAY_5, CHEAP_HOURS, exact_hours=ERWEITERN
    )[-1]
    assert start == datetime(2026, 6, 5, 22, 0, tzinfo=VIENNA)
    assert end == datetime(2026, 6, 6, 6, 0, tzinfo=VIENNA)


def test_verschmolzener_block_ist_von_beiden_tagen_gleich(two_day_data):
    """Die Zusammenfassung ist symmetrisch – beide Tage liefern denselben Block.

    Nur dann ist es gleichgültig, über welchen Tag ein Aufrufer den Block
    findet: ``is_cheap_now`` prüft Vortag + Tag, ``next_cheap_on`` Tag +
    Folgetag.
    """
    assert (
        two_day_data._cheap_blocks_spanning(DAY_5, CHEAP_HOURS, exact_hours=ERWEITERN)[-1]
        == two_day_data._cheap_blocks_spanning(DAY_6, CHEAP_HOURS, exact_hours=ERWEITERN)[0]
    )


def test_auswahl_selbst_bleibt_tageweise(two_day_data):
    """Die tageweise Auswahl selbst bleibt unberührt.

    Zusammengefasst wird ausschließlich für den Jitter; welche Intervalle als
    günstig gelten, ändert sich dadurch nicht.
    """
    # Je Tag unverändert die Stunden 00-05, 09-16 und 22-23 (siehe oben).
    for day in (DAY_5, DAY_6):
        blocks = two_day_data._cheap_blocks(day, CHEAP_HOURS, exact_hours=ERWEITERN)
        assert [(s.hour, e.hour) for s, e, _ in blocks] == [(0, 6), (9, 17), (22, 0)]


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_keine_schaltluecke_um_mitternacht(two_day_data, phase):
    """Der Sensor schaltet am Tageswechsel nicht kurz ab – für jede Phase."""
    moment = datetime(2026, 6, 5, 23, 30, tzinfo=VIENNA)
    last = datetime(2026, 6, 6, 0, 30, tzinfo=VIENNA)
    while moment <= last:
        assert two_day_data.is_cheap_now(moment, CHEAP_HOURS, phase, exact_hours=ERWEITERN), moment
        moment += timedelta(minutes=1)


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75, 0.999])
def test_kein_scheinbarer_neustart_um_mitternacht(two_day_data, phase):
    """Mitten im Block wird kein Neustart um Mitternacht gemeldet.

    Getrennte Blöcke ließen ``next_cheap_on`` um 23:30 auf den 06.06. 00:00
    zeigen, obwohl der Verbraucher längst läuft. Richtig ist der nächste
    *echte* Block, also der 06.06. 09:00 (gejittert innerhalb der Stunde 09).
    """
    next_on = two_day_data.next_cheap_on(
        datetime(2026, 6, 5, 23, 30, tzinfo=VIENNA),
        CHEAP_HOURS,
        phase,
        exact_hours=ERWEITERN,
    )
    assert next_on is not None
    assert next_on.date() == DAY_6
    assert next_on.hour == 9


# --- Die Jitterbreite selbst ------------------------------------------------- #
#
# Alle Tests oben messen Eigenschaften *relativ* zu JITTER_SPAN_SECONDS und
# gelten damit für jede Breite – bewusst so, denn "das Fenster ist L - SPAN
# lang" ist die Zusage, nicht "600". Genau deshalb war die Breite selbst aber
# von keinem Test gepinnt: Sie ließ sich auf 60, 300, 900 oder 1200 Sekunden
# stellen, ohne dass ein einziger Test ansprang.
#
# Die beiden Tests hier schließen diese Lücke – der erste aus der
# Spezifikation abgeleitet, der zweite als bewusste Zweitschrift.


def test_jitterbreite_bleibt_unter_einem_intervall():
    """Der Jitter darf das kleinste reale Intervall nicht aufzehren.

    Aus der Spezifikation abgeleitet (siehe Modul-Docstring von ``jitter.py``):
    Die kleinste real vorkommende Blocklänge ist ein Viertelstunden-Intervall,
    das Raster der API. Ist die Jitterbreite nicht kürzer als das, fällt so ein
    Block auf das ungejitterte Sicherheitsnetz in :func:`jittered_window`
    zurück – die Last-Glättung setzt dann ausgerechnet dort aus, wo die meisten
    Verbraucher gleichzeitig schalten würden, und zwar still.

    Nach oben also 15 Minuten, nach unten mehr als null: Ohne Breite gäbe es
    überhaupt keine Streuung, und der Jitter wäre eine wirkungslose Attrappe.
    """
    viertelstunde_in_sekunden = 15 * 60
    assert 0 < JITTER_SPAN_SECONDS < viertelstunde_in_sekunden


def test_jitterbreite_ist_die_vereinbarten_zehn_minuten():
    """Die Breite steht auf 10 Minuten.

    Das ist bewusst eine **Zweitschrift** des Werts aus ``const.py`` und damit
    keine unabhängige Herleitung – 600 folgt aus einer Abwägung
    (Lastverteilung gegen den festen Laufzeitverlust je Block), nicht aus einer
    Formel. Zweck ist, dass eine Änderung an zwei Stellen bewusst geschehen
    muss, statt sich unbemerkt einzuschleichen: Die Breite kostet jeden
    Verbraucher deterministisch Laufzeit im günstigen Fenster, ein versehentlich
    vervierfachter Wert also 40 statt 10 Minuten pro Block.

    Die Prüfung darüber ist die eigentliche Zusage; diese hier ist die Bremse
    gegen den Zahlendreher.
    """
    assert JITTER_SPAN_SECONDS == 600
