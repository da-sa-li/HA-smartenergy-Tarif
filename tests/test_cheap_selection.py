"""Tests der Günstig-Stunden-Auswahl (Einzelstunden vs. Block, Gleichstand).

Da die Auswahl nur die *Rangfolge* der Gesamtkosten braucht, werden die
günstigsten Intervalle hier von Hand aus den Roh-Bruttopreisen der Fixtures
bestimmt (ohne Netzgebiet ist die Rangfolge monoton im Bruttopreis).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.smartenergy.api import MarketPrice
from custom_components.smartenergy.coordinator import (
    SmartTimesData,
    auswahltag,
    auswahlzeitraum,
)
from tests.conftest import VIENNA

DAY = date(2026, 6, 5)


def _iso(value: str) -> datetime:
    """Kurzschreibweise für ein ISO-8601-datetime (mit Offset)."""
    return datetime.fromisoformat(value)


def _quarter_hours(hour: str) -> list[datetime]:
    """Die vier Viertelstunden-Startzeitpunkte einer Stunde (z. B. '14')."""
    return [_iso(f"2026-06-05T{hour}:{m:02d}:00+02:00") for m in (0, 15, 30, 45)]


def _wrap(prices: list[MarketPrice]) -> SmartTimesData:
    """Kapselt eine Liste von Intervallen als ``SmartTimesData`` (ohne Netzgebiet)."""
    return SmartTimesData(
        tariff="smartTIMES",
        unit="ct/kWh",
        interval_minutes=15,
        include_vat=True,
        prices=prices,
    )


def _synthetic(
    gross_by_slot: dict[str, float], missing: set[str] = frozenset()
) -> SmartTimesData:
    """Ein Tag aus Viertelstunden; nicht genannte Slots sind deutlich teurer.

    Für Gleichstands-Randfälle, die sich in den echten Fixtures nicht ergeben.
    Ohne Netzgebiet ist die Rangfolge monoton im Bruttopreis, die Sollwerte
    lassen sich also direkt aus den hier gesetzten Preisen ablesen.

    ``missing`` lässt die genannten Slots ganz weg und reißt so eine echte
    Lücke ins Tagesraster – der Fall, den der Blockmodus überspringen muss.
    """
    prices = []
    for slot in range(96):
        start = datetime(2026, 6, 5, 0, 0, tzinfo=VIENNA) + timedelta(
            minutes=15 * slot
        )
        label = f"{start.hour:02d}:{start.minute:02d}"
        if label in missing:
            continue
        prices.append(
            MarketPrice(
                start=start,
                end=start + timedelta(minutes=15),
                gross_ct_per_kwh=gross_by_slot.get(label, 50.0),
            )
        )
    return _wrap(prices)


def _partial_day(entries: list[tuple[str, float]]) -> SmartTimesData:
    """Ein Tag aus **genau** den genannten Viertelstunden (``("HH:MM", brutto)``)."""
    prices = []
    for label, gross in entries:
        hour, minute = (int(part) for part in label.split(":"))
        start = datetime(2026, 6, 5, hour, minute, tzinfo=VIENNA)
        prices.append(
            MarketPrice(
                start=start,
                end=start + timedelta(minutes=15),
                gross_ct_per_kwh=gross,
            )
        )
    return _wrap(prices)


def test_einzelmodus_waehlt_die_guenstigsten_viertelstunden(make_data, smartcontrol_payload):
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


def test_einzelmodus_erweitert_bei_gleichstand(make_data, smarttimes_payload):
    """Bei Gleichstand am Schwellwert wird die Auswahl erweitert."""
    # smartTIMES: 32 Intervalle teilen sich den Tiefstpreis 11,316
    # (Stunden 02-03 und 10-15). Ohne Netzgebiet sind sie exakt gleich teuer,
    # daher wird die Auswahl über die 4 strikten hinaus erweitert.
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    all_starts, strict_starts = data._cheap_selection(DAY, 1.0, "individual", False)
    assert len(strict_starts) == 4
    assert len(all_starts) == 32


def test_exact_hours_unterbindet_die_erweiterung(make_data, smarttimes_payload):
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


def test_exact_hours_laesst_die_stundenzahl_durchschlagen(make_data, smarttimes_payload):
    """Mit ``exact_hours`` schlägt die Stundenzahl wieder durch."""
    # Ohne die Option ergibt jede dieser Einstellungen 32 Intervalle.
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    for hours, expected in ((0.25, 1), (1.0, 4), (2.0, 8), (4.0, 16)):
        selected = data.cheap_intervals(DAY, hours, "individual", True)
        assert len(selected) == expected


def test_smartnight_waehlt_die_off_peak_stunden(make_data, smarttimes_payload):
    """Bei smartNIGHT ist die günstige Zone die Nacht (23:00-07:00).

    Off-Peak kostet 11,316 brutto, Peak 14,7108 – ohne Netzgebiet ist die
    Rangfolge monoton im Bruttopreis, günstig sind also genau die 32
    Off-Peak-Intervalle des Kalendertages (00:00-07:00 und 23:00-24:00).
    """
    data = make_data(smarttimes_payload, smartnight=True, grid_zone=None)
    all_starts, strict_starts = data._cheap_selection(DAY, 4.0, "individual", False)

    # 4 h = 16 strikte Intervalle; bei Gleichstand erweitert auf alle 32.
    assert len(strict_starts) == 16
    assert len(all_starts) == 32
    assert all(
        start.hour < 7 or start.hour >= 23 for start in all_starts
    ), "eine Peak-Stunde wurde als günstig markiert"


def test_smartnight_haelt_die_stundenzahl_mit_exact_hours_ein(
    make_data, smarttimes_payload
):
    """Wie bei smartTIMES wirkt die Stundenzahl erst mit ``exact_hours``.

    Die 32 Off-Peak-Intervalle sind exakt gleich teuer; gewählt werden deshalb
    die 16 frühesten, also 00:00-04:00.
    """
    data = make_data(smarttimes_payload, smartnight=True, grid_zone=None)
    all_starts, strict_starts = data._cheap_selection(DAY, 4.0, "individual", True)

    assert all_starts == strict_starts
    assert sorted(all_starts) == [
        _iso("2026-06-05T00:00:00+02:00") + timedelta(minutes=15 * i)
        for i in range(16)
    ]


def test_smartnight_folgt_dem_gesamtpreis_nicht_der_uhrzeit(
    make_data, smarttimes_payload
):
    """Im Kleinwalsertal ist im Sommer das SNAP-Fenster günstiger als die Nacht.

    Das dortige Netznutzungsentgelt fällt im SNAP-Fenster um 17,73 - 14,18 =
    3,55 ct/kWh netto - mehr, als der Peak-Aufschlag ausmacht (30 % von 9,43 =
    2,829 netto). Damit kostet Peak im SNAP-Fenster netto
    12,259 + 0,72 + 14,18 + 0,401 = 27,56 gegenüber
    9,43 + 0,72 + 17,73 + 0,401 = 28,281 für Off-Peak außerhalb.

    Die Auswahl richtet sich also weiterhin nach dem Gesamtpreis und nicht nach
    der Tageszeit; gewählt werden die 16 frühesten der 24 preisgleichen
    SNAP-Intervalle, also 10:00-14:00.
    """
    data = make_data(smarttimes_payload, smartnight=True, grid_zone="kleinwalsertal")
    intervals = data.cheap_intervals(DAY, 4.0, "individual", True)

    assert [p.start for p in intervals] == [
        _iso("2026-06-05T10:00:00+02:00") + timedelta(minutes=15 * i)
        for i in range(16)
    ]
    # 27,56 * 1,2 = 33,072 gegenüber 28,281 * 1,2 = 33,9372 in der Nacht.
    assert data.cheap_cutoff(DAY, 4.0, "individual", True) == pytest.approx(33.072)


def test_blockmodus_waehlt_das_guenstigste_lueckenlose_fenster(make_data, smartcontrol_payload):
    """Der zusammenhängende Block ist das günstigste lückenlose Fenster."""
    # 2 h = 8 zusammenhängende Intervalle mit minimaler Summe.
    # Fenster 13:00-14:45: 4x5,160 + 4x3,851 = 36,044 (günstiger als 12:00-13:45
    # = 46,424 und 14:00-15:45 = 40,68).
    data = make_data(
        smartcontrol_payload, include_vat=True, grid_zone=None, handling_fee_net=1.2
    )
    intervals = data.cheap_intervals(DAY, 2.0, "consecutive")
    assert sorted(p.start for p in intervals) == _quarter_hours("13") + _quarter_hours("14")


def test_blockmodus_behaelt_die_laenge_bei_gleichstand(
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
    start, end, exceeds = blocks[0]
    assert start == _iso("2026-06-05T02:00:00+02:00")
    assert end == _iso("2026-06-05T03:00:00+02:00")
    # Ohne Erweiterung gibt es im Blockmodus keine Überschuss-Intervalle mehr.
    assert exceeds is False


@pytest.mark.parametrize(
    "gross",
    [
        {"02:00": 10.0, "02:15": 10.0, "10:00": 10.0, "10:15": 5.0, "10:30": 5.0},
        {"02:00": 10.0, "02:15": 10.0, "10:00": 5.0, "10:15": 10.0, "10:30": 5.0},
    ],
    ids=["ueberschuss-am-blockanfang", "ueberschuss-in-blockmitte"],
)
def test_ueberschuss_gilt_fuer_den_ganzen_block(gross):
    """Ein Überschuss-Intervall zählt auch, wenn es nicht am Blockende liegt.

    Bei 1 h (= 4 Intervalle) sind die vier günstigsten die beiden 5,0er sowie
    02:00 und 02:15 (die frühesten am Schwellwert 10,0). Das dritte
    10,0-Intervall liegt im Block 10:00-10:45 und kommt nur durch den
    Gleichstand hinzu, geht also über die eingestellte Stundenzahl hinaus –
    einmal am Blockanfang, einmal in der Blockmitte.

    Die frühere Prüfung sah nur das *letzte* Intervall eines Blocks und meldete
    beide Fälle fälschlich als unauffällig.
    """
    data = _synthetic(gross)
    blocks = {
        start.hour: exceeds
        for start, _, exceeds in data._cheap_blocks(DAY, 1.0, "individual", False)
    }
    assert blocks == {2: False, 10: True}


def test_blockmodus_ueberspringt_keine_luecke():
    """Ein Fenster darf keine Lücke im Tagesraster überspannen.

    09:30 und 09:45 sind mit 1,0 die günstigsten Intervalle des Tages, direkt
    danach fehlen 10:00 und 10:15. Jedes 4er-Fenster, das die beiden mitnehmen
    wollte, müsste über die Lücke greifen und ist damit ungültig – ein Block
    „am Stück“ wäre es ja nicht. Das günstigste lückenlose Fenster ist deshalb
    13:00-14:00 (4 x 2,0 = 8,0); alle übrigen Intervalle kosten 50,0.
    """
    data = _synthetic(
        {
            "09:30": 1.0,
            "09:45": 1.0,
            "13:00": 2.0,
            "13:15": 2.0,
            "13:30": 2.0,
            "13:45": 2.0,
        },
        missing={"10:00", "10:15"},
    )
    blocks = data._cheap_blocks(DAY, 1.0, "consecutive")  # 1 h = 4 Intervalle
    assert len(blocks) == 1
    assert blocks[0][:2] == (
        _iso("2026-06-05T13:00:00+02:00"),
        _iso("2026-06-05T14:00:00+02:00"),
    )


def test_blockmodus_faellt_auf_die_einzelauswahl_zurueck():
    """Passt gar kein lückenloses Fenster, greift die Einzelauswahl.

    Sechs Intervalle mit einer Lücke um 00:45: Jedes der drei möglichen
    4er-Fenster überspannt sie. Erwartet wird der Rückfall auf die vier
    günstigsten Einzelintervalle (4,0 / 5,0 / 6,0 / 7,0) – und zwar ohne
    Gleichstands-Erweiterung, damit die Zusage einer festen Länge auch in
    diesem Pfad gilt.
    """
    data = _partial_day(
        [
            ("00:00", 9.0),
            ("00:15", 8.0),
            ("00:30", 7.0),
            ("01:00", 6.0),
            ("01:15", 5.0),
            ("01:30", 4.0),
        ]
    )
    all_starts, strict_starts = data._cheap_selection(DAY, 1.0, "consecutive")
    assert all_starts == strict_starts
    assert sorted(all_starts) == [
        _iso("2026-06-05T00:30:00+02:00"),
        _iso("2026-06-05T01:00:00+02:00"),
        _iso("2026-06-05T01:15:00+02:00"),
        _iso("2026-06-05T01:30:00+02:00"),
    ]


def test_blockmodus_ignoriert_exact_hours(make_data, smarttimes_payload):
    """``exact_hours`` ist im Blockmodus wirkungslos – dort gilt sie immer."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    assert data._cheap_blocks(DAY, 1.0, "consecutive", False) == data._cheap_blocks(
        DAY, 1.0, "consecutive", True
    )


# --- Auswahltag des Blockmodus: 20 bis 20 Uhr (Issue #114) ------------------ #
#
# Im Blockmodus reicht der Auswahltag ``D`` von 20:00 Uhr des Vortags bis 20:00
# Uhr an ``D``. So kann ein Block über Mitternacht reichen; der Abend von ``D``
# gehört dagegen schon zum Auswahltag ``D + 1``.

NEXT_DAY = date(2026, 6, 6)


def _zwei_tage(
    gross_by_slot: dict[str, float],
    *,
    tage: tuple[int, ...] = (5, 6),
    retained: dict[str, float] | None = None,
) -> SmartTimesData:
    """Viertelstunden der genannten Junitage; Schlüssel ``"TT HH:MM"``.

    Nicht genannte Slots kosten 50,0 und sind damit deutlich teurer als alles,
    was ein Test eigens setzt. Ohne Netzgebiet ist die Rangfolge monoton im
    Bruttopreis, die Sollwerte lassen sich direkt aus den Preisen ablesen.

    ``retained`` landet in ``retained_prices`` – so, wie der Koordinator den
    Vortagsabend nach dem täglichen Abruf weiterreicht.
    """

    def slot(label: str, gross: float) -> MarketPrice:
        tag, uhrzeit = label.split(" ")
        hour, minute = (int(part) for part in uhrzeit.split(":"))
        start = datetime(2026, 6, int(tag), hour, minute, tzinfo=VIENNA)
        return MarketPrice(
            start=start, end=start + timedelta(minutes=15), gross_ct_per_kwh=gross
        )

    prices = []
    for tag in tage:
        for index in range(96):
            start = datetime(2026, 6, tag, tzinfo=VIENNA) + timedelta(minutes=15 * index)
            label = f"{tag:02d} {start.hour:02d}:{start.minute:02d}"
            prices.append(slot(label, gross_by_slot.get(label, 50.0)))
    data = _wrap(prices)
    data.retained_prices = [slot(label, gross) for label, gross in (retained or {}).items()]
    return data


def _slots(tag: int, von: str, bis: str, gross: float) -> dict[str, float]:
    """Gleicher Preis für alle Viertelstunden von ``von`` bis ausschließlich ``bis``."""
    start = datetime(2026, 6, tag, *(int(p) for p in von.split(":")), tzinfo=VIENNA)
    ende = datetime(2026, 6, tag, *(int(p) for p in bis.split(":")), tzinfo=VIENNA)
    if ende <= start:
        ende += timedelta(days=1)
    result = {}
    while start < ende:
        result[f"{start.day:02d} {start.hour:02d}:{start.minute:02d}"] = gross
        start += timedelta(minutes=15)
    return result


def test_auswahltag_des_blockmodus_beginnt_um_20_uhr():
    """Ab 20:00 Uhr gilt im Blockmodus schon der Auswahltag des Folgetags."""
    vor = datetime(2026, 6, 5, 19, 59, tzinfo=VIENNA)
    ab = datetime(2026, 6, 5, 20, 0, tzinfo=VIENNA)

    assert auswahltag(vor, "consecutive") == DAY
    assert auswahltag(ab, "consecutive") == NEXT_DAY
    # Im Einzelstunden-Modus bleibt es beim Kalendertag.
    assert auswahltag(ab, "individual") == DAY
    assert auswahlzeitraum(NEXT_DAY, "consecutive") == (ab, ab + timedelta(days=1))
    assert auswahlzeitraum(NEXT_DAY, "individual") == (
        datetime(2026, 6, 6, tzinfo=VIENNA),
        datetime(2026, 6, 7, tzinfo=VIENNA),
    )


def test_auswahltag_folgt_an_der_zeitumstellung_der_wanduhr():
    """Am Ende der Sommerzeit ist der Auswahltag 25 Stunden lang.

    In der Nacht auf den 25.10.2026 wird die Uhr von 03:00 auf 02:00
    zurückgestellt. Der Auswahltag reicht trotzdem von 20:00 bis 20:00 Uhr
    Wanduhrzeit – vorher mit Sommerzeit-Offset +02:00, danach mit +01:00.
    """
    start, ende = auswahlzeitraum(date(2026, 10, 25), "consecutive")

    assert start.isoformat() == "2026-10-24T20:00:00+02:00"
    assert ende.isoformat() == "2026-10-25T20:00:00+01:00"
    # In UTC rechnen: Zwei Zeitpunkte derselben Zone zieht Python als
    # Wanduhrzeiten voneinander ab und käme so auf 24 Stunden.
    assert ende.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=25)


def test_blockmodus_waehlt_ein_fenster_ueber_mitternacht():
    """Das günstigste Fenster über Mitternacht wird als ein Block gewählt.

    Das Beispiel aus Issue #114: 23:00-05:00 kostet 10,0 (Off-Peak mit WiNAP),
    05:00-07:00 kostet 12,0 (Off-Peak ohne WiNAP). Für 6 h ist 23:00-05:00 mit
    24 x 10,0 = 240,0 das günstigste Fenster. Je Kalendertag stand nur
    00:00-06:00 zur Wahl (20 x 10,0 + 4 x 12,0 = 248,0).
    """
    data = _zwei_tage(
        _slots(5, "23:00", "05:00", 10.0) | _slots(6, "05:00", "07:00", 12.0)
    )

    blocks = data._cheap_blocks(NEXT_DAY, 6.0, "consecutive")

    assert blocks == (
        (
            datetime(2026, 6, 5, 23, 0, tzinfo=VIENNA),
            datetime(2026, 6, 6, 5, 0, tzinfo=VIENNA),
            False,
        ),
    )


def test_blockmodus_schneidet_an_der_20_uhr_grenze():
    """Ein Block reicht nie über 20:00 Uhr – dort beginnt der nächste Auswahltag.

    Am 05.06. kostet 19:00-21:00 je 10,0, sonst alles 50,0. Für 2 h nimmt der
    Auswahltag des 05.06. (bis 20:00) die Stunde 19:00-20:00 mit, das
    günstigste Fenster ist also 18:00-20:00 (4 x 50,0 + 4 x 10,0). Der
    Auswahltag des 06.06. beginnt um 20:00 und nimmt 20:00-21:00 mit, also
    20:00-22:00 (das früheste der beiden gleich teuren Fenster).
    """
    data = _zwei_tage(_slots(5, "19:00", "21:00", 10.0))

    assert data._cheap_blocks(DAY, 2.0, "consecutive")[0][:2] == (
        datetime(2026, 6, 5, 18, 0, tzinfo=VIENNA),
        datetime(2026, 6, 5, 20, 0, tzinfo=VIENNA),
    )
    assert data._cheap_blocks(NEXT_DAY, 2.0, "consecutive")[0][:2] == (
        datetime(2026, 6, 5, 20, 0, tzinfo=VIENNA),
        datetime(2026, 6, 5, 22, 0, tzinfo=VIENNA),
    )


def test_blockmodus_wartet_auf_die_preise_des_auswahltags():
    """Fehlen die Morgen-Preise, wählt der Blockmodus gar nichts.

    Vorhanden ist nur der 05.06.; 21:00-22:00 ist dort mit 1,0 die günstigste
    Stunde. Sie gehört zum Auswahltag des 06.06., dessen übrige 20 Stunden
    fehlen. Gewählt wird trotzdem nicht: Sonst fiele die Wahl allein auf den
    Vortagsabend, also gerade auf die Abendspitze.
    """
    data = _zwei_tage(_slots(5, "21:00", "22:00", 1.0), tage=(5,))
    abends = datetime(2026, 6, 5, 20, 30, tzinfo=VIENNA)

    assert data.cheap_intervals(NEXT_DAY, 1.0, "consecutive") == []
    assert data.is_cheap_now(
        datetime(2026, 6, 5, 21, 30, tzinfo=VIENNA), 1.0, 0.0, "consecutive"
    ) is False
    assert data.next_cheap_on(abends, 1.0, 0.0, "consecutive") is None


def test_blockmodus_nutzt_den_behaltenen_vortagsabend():
    """``retained_prices`` füllen den Vortagsabend des Auswahltags auf.

    Die API liefert nur noch den 06.06.; der Koordinator hat 20:00-24:00 des
    05.06. behalten, 23:00-24:00 kostet dort 10,0. Am 06.06. kostet
    00:00-01:00 ebenfalls 10,0. Für 2 h ist 23:00-01:00 mit 8 x 10,0 das
    günstigste Fenster. Ohne den behaltenen Abend bliebe nur 00:00-02:00
    (4 x 10,0 + 4 x 50,0).
    """
    data = _zwei_tage(
        _slots(6, "00:00", "01:00", 10.0),
        tage=(6,),
        retained=_slots(5, "20:00", "23:00", 50.0) | _slots(5, "23:00", "00:00", 10.0),
    )

    assert data._cheap_blocks(NEXT_DAY, 2.0, "consecutive")[0][:2] == (
        datetime(2026, 6, 5, 23, 0, tzinfo=VIENNA),
        datetime(2026, 6, 6, 1, 0, tzinfo=VIENNA),
    )


def test_einzelmodus_ignoriert_den_behaltenen_vortagsabend():
    """Der Einzelstunden-Modus wählt weiter je Kalendertag.

    Dieselben Daten wie im Test darüber: Für 1 h ist 00:00-01:00 (10,0) die
    günstigste Stunde des 06.06. Die gleich teure Stunde 23:00-24:00 des 05.06.
    gehört zu einem anderen Kalendertag und bleibt außen vor.
    """
    data = _zwei_tage(
        _slots(6, "00:00", "01:00", 10.0),
        tage=(6,),
        retained=_slots(5, "23:00", "00:00", 10.0),
    )

    assert [p.start for p in data.cheap_intervals(NEXT_DAY, 1.0, "individual", True)] == [
        datetime(2026, 6, 6, 0, 0, tzinfo=VIENNA) + timedelta(minutes=15 * i)
        for i in range(4)
    ]


def test_smartnight_block_beginnt_am_vorabend(make_data, smarttimes_payload):
    """Bei smartNIGHT beginnt ein Nacht-Block um 23:00 Uhr des Vortags.

    Off-Peak (23:00-07:00) kostet durchgehend 11,316, Peak 14,7108. Ohne
    Netzgebiet sind damit alle 6-h-Fenster in 23:00-07:00 gleich teuer
    (23-05, 00-06 und 01-07, jeweils die Viertelstunden-Zwischenschritte
    eingeschlossen); gewählt wird das früheste. Je Kalendertag war das
    00:00-06:00, jetzt ist es 23:00-05:00 – sobald der WiNAP (23-05) Sätze hat,
    ist es auch das günstigste.
    """
    data = make_data(smarttimes_payload, smartnight=True, grid_zone=None)

    blocks = data._cheap_blocks(NEXT_DAY, 6.0, "consecutive")

    assert [block[:2] for block in blocks] == [
        (_iso("2026-06-05T23:00:00+02:00"), _iso("2026-06-06T05:00:00+02:00"))
    ]


# --- Herbstumstellung mit der echten Antwort (Issue #126) ------------------- #
#
# Fixture smarttimes_zeitumstellung_herbst.json, 25.10.2026 (Bruttopreise in ct/kWh, ohne
# Netzgebiet ist die Rangfolge monoton darin):
#   00:00-02:00 Sommerzeit                25,476
#   02:00 Sommerzeit - 04:00 Winterzeit   22,152  (drei echte Stunden: Die Uhr
#                                                  läuft 02:00-02:59 zweimal)
#   04:00-06:00 25,476 | 06:00-09:00 31,02 | 09:00-10:00 25,476
#   10:00-16:00                           22,152
#   16:00-17:00 25,476 | 17:00-22:00 31,02 | 22:00-23:00 25,476 (dann endet sie)
UMSTELLUNGSTAG = date(2026, 10, 25)


def test_aktueller_preis_deckt_die_doppelte_stunde_ab(
    make_data, smarttimes_zeitumstellung_herbst_payload
):
    """In beiden Durchläufen von 02:30 gilt ein Preis – je ein eigener Eintrag.

    02:30 Sommerzeit ist 00:30 UTC, 02:30 Winterzeit 01:30 UTC. Vor der
    Korrektur hatte der erste Zeitpunkt keinen Preis.
    """
    data = make_data(smarttimes_zeitumstellung_herbst_payload)

    sommer = data.current(datetime(2026, 10, 25, 0, 30, tzinfo=UTC))
    winter = data.current(datetime(2026, 10, 25, 1, 30, tzinfo=UTC))

    assert sommer is not None and winter is not None
    assert sommer.gross_ct_per_kwh == winter.gross_ct_per_kwh == 22.152
    assert sommer.start == _iso("2026-10-25T02:30:00+02:00")
    assert winter.start == _iso("2026-10-25T02:30:00+01:00")
    tag = data.for_day(UMSTELLUNGSTAG)
    assert len(tag) == len({p.start for p in tag})


def test_aktueller_preis_von_smartcontrol_folgt_der_uhr(
    make_data, smartcontrol_zeitumstellung_herbst_payload
):
    """Bei smartCONTROL gilt in jedem Durchlauf von 02:30 der eigene Börsenpreis.

    Aus ``smartcontrol_zeitumstellung_herbst.json``: erster Durchlauf 25,339,
    zweiter 25,092 ct/kWh. Vorher fehlte um 00:30 UTC der Preis, und um
    01:30 UTC galt 25,339 – der Preis der Stunde davor.
    """
    data = make_data(smartcontrol_zeitumstellung_herbst_payload)

    sommer = data.current(datetime(2026, 10, 25, 0, 30, tzinfo=UTC))
    winter = data.current(datetime(2026, 10, 25, 1, 30, tzinfo=UTC))

    assert sommer is not None and sommer.gross_ct_per_kwh == 25.339
    assert winter is not None and winter.gross_ct_per_kwh == 25.092


def test_einzelmodus_haelt_die_stundenzahl_an_der_herbstumstellung(
    make_data, smarttimes_zeitumstellung_herbst_payload
):
    """4 Stunden bleiben 4 Stunden, auch über die doppelte Stunde.

    4 h = 16 Viertelstunden zu 22,152. Bei Gleichstand entscheidet die
    Startzeit: zuerst die 12 der Nacht (02:00 Sommerzeit bis 04:00
    Winterzeit), dann 10:00-11:00. Vorher zählten die vier doppelt
    beschrifteten Einträge zweimal, und der Sensor lief nur 3 Stunden.
    """
    data = make_data(smarttimes_zeitumstellung_herbst_payload)

    blocks = data._cheap_blocks(UMSTELLUNGSTAG, 4.0, "individual", True)

    assert [block[:2] for block in blocks] == [
        (_iso("2026-10-25T02:00:00+02:00"), _iso("2026-10-25T04:00:00+01:00")),
        (_iso("2026-10-25T10:00:00+01:00"), _iso("2026-10-25T11:00:00+01:00")),
    ]
    assert sum((ende - start for start, ende, _ in blocks), timedelta()) == timedelta(
        hours=4
    )


def test_blockmodus_laeuft_ueber_die_doppelte_stunde(
    make_data, smarttimes_zeitumstellung_herbst_payload
):
    """Ein Block darf durch die Zeitumstellung hindurch laufen.

    1,5 h zu 22,152 sind nachts wie mittags gleich teuer, gewählt wird das
    früheste Fenster: ab 02:00 Sommerzeit (00:00 UTC) bis 01:30 UTC, also
    02:30 Winterzeit. Vorher galten die doppelt beschrifteten Einträge als
    Lücke, und der Block wich auf 10:00 aus.
    """
    data = make_data(smarttimes_zeitumstellung_herbst_payload)

    blocks = data._cheap_blocks(UMSTELLUNGSTAG, 1.5, "consecutive")

    assert [block[:2] for block in blocks] == [
        (_iso("2026-10-25T02:00:00+02:00"), _iso("2026-10-25T02:30:00+01:00"))
    ]
