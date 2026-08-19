"""Tests der Günstig-Stunden-Auswahl (Einzelstunden vs. Block, Gleichstand).

Da die Auswahl nur die *Rangfolge* der Gesamtkosten braucht, werden die
günstigsten Intervalle hier von Hand aus den Roh-Bruttopreisen der Fixtures
bestimmt (ohne Netzgebiet ist die Rangfolge monoton im Bruttopreis).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from custom_components.smartenergy.coordinator import SmartTimesData

DAY = date(2026, 6, 5)


def _iso(value: str) -> datetime:
    """Kurzschreibweise für ein ISO-8601-datetime (mit Offset)."""
    return datetime.fromisoformat(value)


def _quarter_hours(hour: str) -> list[datetime]:
    """Die vier Viertelstunden-Startzeitpunkte einer Stunde (z. B. '14')."""
    return [_iso(f"2026-06-05T{hour}:{m:02d}:00+02:00") for m in (0, 15, 30, 45)]


def test_individual_picks_cheapest_quarter_hours(make_data, smartcontrol_payload):
    """Einzelstunden-Modus wählt die günstigsten Viertelstunden des Tages."""
    # smartCONTROL hat unterschiedliche Preise -> klare Rangfolge.
    # Günstigste Stunde am 05.06. ist 14:00 (gross 3,851).
    data = make_data(
        smartcontrol_payload, include_vat=True, grid_zone=None, handling_fee_net=1.2
    )
    intervals = data.cheap_intervals(DAY, 1.0, "individual")  # 1 h = 4 Intervalle
    assert sorted(p.start for p in intervals) == _quarter_hours("14")
    # Schwellwert = Gesamtpreis von 3,851:
    # netto 3,2092 + (0,72 + 1,2) = 5,1292 ; brutto 5,1292 * 1,2 = 6,15504 -> 6,1550
    assert data.cheap_cutoff(DAY, 1.0, "individual") == pytest.approx(6.1550)


def test_individual_tie_expands_selection(make_data, smarttimes_payload):
    """Bei Gleichstand am Schwellwert wird die Auswahl erweitert."""
    # smartTIMES: 32 Intervalle teilen sich den Tiefstpreis 11,316
    # (Stunden 02-03 und 10-15). Ohne Netzgebiet sind sie exakt gleich teuer,
    # daher wird die Auswahl über die 4 strikten hinaus erweitert.
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    all_starts, strict_starts = data._cheap_selection(DAY, 1.0, "individual")
    assert len(strict_starts) == 4
    assert len(all_starts) == 32


def test_individual_exact_hours_suppresses_expansion(make_data, smarttimes_payload):
    """Mit ``exact_hours`` bleibt es bei genau der eingestellten Stundenzahl.

    Ohne die Option liefert smartTIMES wegen seiner nur drei Preisstufen für
    *jede* Einstellung zwischen 0,25 h und 8 h dieselben 32 Intervalle – die
    Stundenzahl wäre damit faktisch wirkungslos (siehe Test darüber).
    """
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    all_starts, strict_starts = data._cheap_selection(
        DAY, 1.0, "individual", True
    )
    assert len(strict_starts) == 4
    assert all_starts == strict_starts
    # Gewählt sind die 4 frühesten der 32 preisgleichen Intervalle: Stunde 02.
    assert sorted(all_starts) == _quarter_hours("02")


def test_exact_hours_scales_with_the_setting(make_data, smarttimes_payload):
    """Mit ``exact_hours`` schlägt die Stundenzahl wieder durch."""
    # Ohne die Option ergibt jede dieser Einstellungen 32 Intervalle.
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    for hours, expected in ((0.25, 1), (1.0, 4), (2.0, 8), (4.0, 16)):
        selected = data.cheap_intervals(DAY, hours, "individual", True)
        assert len(selected) == expected


def test_consecutive_block_crosses_hour_boundary(make_data, smartcontrol_payload):
    """Der zusammenhängende Block ist das günstigste lückenlose Fenster."""
    # 2 h = 8 zusammenhängende Intervalle mit minimaler Summe.
    # Fenster 13:00-14:45: 4x5,160 + 4x3,851 = 36,044 (günstiger als 12:00-13:45
    # = 46,424 und 14:00-15:45 = 40,68).
    data = make_data(
        smartcontrol_payload, include_vat=True, grid_zone=None, handling_fee_net=1.2
    )
    intervals = data.cheap_intervals(DAY, 2.0, "consecutive")
    assert sorted(p.start for p in intervals) == _quarter_hours("13") + _quarter_hours("14")


def test_consecutive_keeps_the_requested_length_on_tie(
    make_data, smarttimes_payload
):
    """Der Block behält bei Gleichstand exakt die angeforderte Länge.

    Eine feste Fensterlänge ist der Zweck dieser Betriebsart (Geräte mit fester
    Laufzeit, die nicht unterbrochen werden dürfen). Eine Verlängerung bei
    Gleichstand hob genau das auf: Bei smartTIMES reicht der Tiefstpreis 11,316
    lückenlos von 02:00 bis 04:00, aus der angeforderten Stunde wurden so zwei.
    Grenzen preisgleiche Intervalle an, ist die Wahl zwischen ihnen ohnehin
    beliebig – dann gilt das angeforderte Fenster (frühestes bei Gleichstand).
    """
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    blocks = data._cheap_blocks(DAY, 1.0, "consecutive")
    assert len(blocks) == 1
    start, end, soft_end = blocks[0]
    assert start == _iso("2026-06-05T02:00:00+02:00")
    assert end == _iso("2026-06-05T03:00:00+02:00")
    # Ohne Erweiterung gibt es im Blockmodus keine Überschuss-Intervalle mehr.
    assert soft_end is False


def test_consecutive_ignores_exact_hours_option(make_data, smarttimes_payload):
    """``exact_hours`` ist im Blockmodus wirkungslos – dort gilt sie immer."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    assert data._cheap_blocks(DAY, 1.0, "consecutive", False) == data._cheap_blocks(
        DAY, 1.0, "consecutive", True
    )
