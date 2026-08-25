"""Tests des Rechen-Caches in ``SmartTimesData`` (Issue #74).

Gemessen wird nicht die Laufzeit – die hängt an der Maschine –, sondern die
Zahl der *tatsächlichen* Berechnungen. Sie ist deterministisch und von Hand
herleitbar: Über eine vollständige Sensor-Auswertung hinweg darf jedes Intervall
höchstens einmal bewertet und jede Auswahl je ``(Tag, Stundenzahl, Modus,
exact_hours)`` höchstens einmal gebildet werden.

Bezugspunkt ist die im Issue gemessene Ausgangslage: 992 Bewertungen im
Einzelstunden- und 12.976 im Blockmodus – je Sensor und Minute, im Event-Loop
von Home Assistant.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

import pytest

from custom_components.smartenergy.coordinator import SmartTimesData
from tests.conftest import VIENNA

DAY = date(2026, 6, 5)
# Mitten am Tag, damit die Auswertung Vor- und Folgetag mit einbezieht.
NOW = datetime(2026, 6, 5, 12, 30, tzinfo=VIENNA)
CHEAP_HOURS = 4.0
PHASE = 0.25

# Die drei Methoden, hinter denen die eigentliche Rechenarbeit steckt; die
# gleichnamigen öffentlichen Methoden bedienen davor den Cache.
COMPUTE_METHODS = (
    "_compute_all_in_value",
    "_compute_cheap_selection",
    "_compute_cheap_blocks",
)


@pytest.fixture(name="berechnungen")
def _berechnungen(monkeypatch):
    """Zählt die echten, *nicht* aus dem Cache bedienten Berechnungen.

    Gepatcht wird die Klasse, nicht die Instanz: ``SmartTimesData`` ist eine
    ``slots``-Dataclass und nimmt keine zusätzlichen Attribute an.
    """
    zaehler: Counter[str] = Counter()

    for name in COMPUTE_METHODS:
        original = getattr(SmartTimesData, name)

        def wrapper(self, *args, _original=original, _name=name, **kwargs):
            zaehler[_name] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(SmartTimesData, name, wrapper)

    return zaehler


def _auswerten(
    data: SmartTimesData,
    mode: str = "individual",
    exact_hours: bool = False,
    phase: float = PHASE,
) -> tuple:
    """Stellt eine vollständige Auswertung eines Sensors nach.

    Dieselben Aufrufe stößt ``binary_sensor.py`` je Update über ``is_on`` und
    ``extra_state_attributes`` an.
    """
    return (
        data.is_cheap_now(NOW, CHEAP_HOURS, phase, mode, exact_hours),
        [
            (p.start, p.end, data.all_in_value(p))
            for p in data.cheap_intervals(DAY, CHEAP_HOURS, mode, exact_hours)
        ],
        data.jittered_cheap_windows(DAY, CHEAP_HOURS, phase, mode, exact_hours),
        data.next_cheap_on(NOW, CHEAP_HOURS, phase, mode, exact_hours),
        data.cheap_cutoff(DAY, CHEAP_HOURS, mode, exact_hours),
    )


@pytest.fixture(name="tagesdaten")
def _tagesdaten(make_data, smarttimes_payload):
    """``SmartTimesData`` mit Netzgebiet – so greifen auch die SNAP-Fenster."""
    return make_data(smarttimes_payload, include_vat=True, grid_zone="wien")


@pytest.mark.parametrize("mode", ["individual", "consecutive"])
def test_jedes_intervall_wird_hoechstens_einmal_bewertet(
    tagesdaten, berechnungen, mode
):
    """Eine volle Auswertung bewertet jedes Intervall genau einmal.

    Die smartTIMES-Fixture deckt zwei Kalendertage zu je 96 Viertelstunden ab;
    die Auswertung berührt beide (``is_cheap_now`` prüft Vortag und Tag,
    ``next_cheap_on`` Tag und Folgetag). Mehr als 2 x 96 = 192 Bewertungen kann
    es damit nicht geben – und weniger auch nicht, da jeder der beiden Tage
    vollständig in eine Rangfolge gebracht wird.
    """
    _auswerten(tagesdaten, mode)
    assert berechnungen["_compute_all_in_value"] == 192


@pytest.mark.parametrize("mode", ["individual", "consecutive"])
def test_kein_schluessel_wird_zweimal_berechnet(tagesdaten, berechnungen, mode):
    """Jeder Cache-Schlüssel entsteht aus genau einer Berechnung.

    Das ist die eigentliche Zusage des Caches – unabhängig davon, wie viele
    Tage eine Auswertung gerade berührt.
    """
    _auswerten(tagesdaten, mode)
    assert berechnungen["_compute_all_in_value"] == len(tagesdaten._value_cache)
    assert berechnungen["_compute_cheap_selection"] == len(
        tagesdaten._selection_cache
    )
    assert berechnungen["_compute_cheap_blocks"] == len(tagesdaten._block_cache)


def test_zweiter_sensor_gleicher_einstellung_rechnet_nichts_nach(
    tagesdaten, berechnungen
):
    """Gleich konfigurierte Sensoren teilen sich die Auswahl.

    Alle Sensoren lesen dieselbe ``coordinator.data``-Instanz. Der Jitter geht
    bewusst nicht in den Cache-Schlüssel ein: Er wirkt erst auf die fertigen
    Blöcke, ein zweiter Sensor mit anderer Phase darf also keine einzige
    Berechnung mehr auslösen.
    """
    _auswerten(tagesdaten, "consecutive", phase=0.25)
    nach_erstem = dict(berechnungen)
    _auswerten(tagesdaten, "consecutive", phase=0.9)
    assert dict(berechnungen) == nach_erstem


def test_cache_aendert_das_ergebnis_nicht(make_data, smarttimes_payload):
    """Warme und frische Instanz liefern dasselbe Ergebnis.

    Sonst wäre der Cache kein Cache, sondern eine Verhaltensänderung.
    """
    for mode in ("individual", "consecutive"):
        kalt = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")
        frisch = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")
        erste = _auswerten(kalt, mode)
        assert _auswerten(kalt, mode) == erste  # dieselbe, nun warme Instanz
        assert _auswerten(frisch, mode) == erste  # eine unberührte Instanz


def test_zusammenfassung_laesst_die_gecachten_bloecke_unberuehrt(
    make_data, smarttimes_payload
):
    """``_cheap_blocks_spanning`` darf den gecachten Tagesstand nicht verändern.

    Die Zusammenfassung über die Tagesgrenze ersetzt den ersten bzw. letzten
    Block. Ihre Vorlage stammt aus dem Cache – arbeitete sie darauf, schlüge der
    zusammengefasste Block auf die *tageweise* Auswahl durch, die bewusst
    tageweise bleibt (siehe ``test_jitter.test_selection_itself_stays_per_day``).
    """
    # Ohne Netzgebiet, damit die in test_jitter.py hergeleitete Blockaufteilung
    # gilt: Bei 9 h grenzt der letzte Block des 05.06. (22:00-24:00) exakt an
    # den ersten des 06.06. (00:00-06:00).
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    assert [(s.hour, e.hour) for s, e, _ in data._cheap_blocks(DAY, 9.0, exact_hours=False)] == [
        (0, 6),
        (9, 17),
        (22, 0),
    ]

    zusammengefasst = data._cheap_blocks_spanning(DAY, 9.0, exact_hours=False)

    # Die Zusammenfassung hat gegriffen – der letzte Block reicht in den 06.06.
    assert zusammengefasst[-1][1] == datetime(2026, 6, 6, 6, 0, tzinfo=VIENNA)
    # ... und der tageweise Stand ist derselbe geblieben. Bewusst erneut gegen
    # die von Hand hergeleiteten Stundenpaare geprüft statt gegen einen vorher
    # gezogenen Schnappschuss: Der wäre dasselbe (unveränderliche) Objekt und
    # der Vergleich damit tautologisch.
    assert [(s.hour, e.hour) for s, e, _ in data._cheap_blocks(DAY, 9.0, exact_hours=False)] == [
        (0, 6),
        (9, 17),
        (22, 0),
    ]
