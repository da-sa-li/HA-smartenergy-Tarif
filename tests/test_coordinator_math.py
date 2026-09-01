"""Tests der Preis-Mathematik in ``SmartTimesData``.

Kernkonvention (CLAUDE.md): Nebenkosten werden **netto** summiert, die USt. wird
**einmal am Ende** auf die Summe angewendet. Jede Erwartung ist als Handrechnung
im Kommentar dokumentiert.

Bezugszahlen (alle netto, ct/kWh):
* Abgaben am 05.06.2026: 0,1 + 0,62 = 0,72
* Netz Wien, Regelzeit:  6,98 + 0,700 = 7,68
* Netz Wien, SNAP:       5,58 + 0,700 = 6,28
* Abwicklungsgebühr smartCONTROL: 1,2
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.smartenergy.api import MarketPrice
from custom_components.smartenergy.coordinator import SmartTimesData
from custom_components.smartenergy.grid_fees import GridZone, get_zone
from tests.conftest import VIENNA


def _iso(value: str) -> datetime:
    """Kurzschreibweise für ein ISO-8601-datetime (mit Offset)."""
    return datetime.fromisoformat(value)


def _tagesintervalle(data: SmartTimesData) -> tuple[MarketPrice, ...]:
    """Alle Intervalle des 05.06.2026 (dem ersten Tag beider Fixtures)."""
    return data.for_day(datetime(2026, 6, 5, tzinfo=VIENNA).date())


def _price_at(data: SmartTimesData, value: str) -> MarketPrice:
    """Liefert den Preis-Eintrag mit dem Startzeitpunkt ``value``."""
    target = _iso(value)
    for price in data.prices:
        if price.start == target:
            return price
    raise AssertionError(f"kein Intervall mit Start {value}")


# --- smartTIMES (keine Abwicklungsgebühr) ---------------------------------- #


def test_gesamtpreis_smarttimes_im_snap_fenster_wien(make_data, smarttimes_payload):
    """Gesamtpreis im SNAP-Fenster mit Netzgebiet Wien (brutto)."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")
    price = _price_at(data, "2026-06-05T14:00:00+02:00")  # 14 Uhr -> SNAP aktiv
    # netto AP 11,316/1,2 = 9,43 ; + Abgaben 0,72 + Netz(SNAP) 6,28 = 16,43
    # brutto = 16,43 * 1,2 = 19,716
    assert data.all_in_value(price) == pytest.approx(19.716)


def test_gesamtpreis_smarttimes_ausserhalb_des_snap_fensters_wien(make_data, smarttimes_payload):
    """Gesamtpreis außerhalb des SNAP-Fensters (Regel-Netzentgelt)."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")
    price = _price_at(data, "2026-06-05T18:00:00+02:00")  # 18 Uhr -> kein SNAP
    # netto AP 15,852/1,2 = 13,21 ; + 0,72 + Netz(Regel) 7,68 = 21,61
    # brutto = 21,61 * 1,2 = 25,932
    assert data.all_in_value(price) == pytest.approx(25.932)


def test_gesamtpreis_smarttimes_ohne_netzgebiet(make_data, smarttimes_payload):
    """Ohne Netzgebiet fließen nur die bundesweiten Abgaben ein."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    price = _price_at(data, "2026-06-05T14:00:00+02:00")
    # netto 9,43 + 0,72 = 10,15 ; brutto = 12,18
    assert data.all_in_value(price) == pytest.approx(12.18)


def test_gesamtpreis_im_netto_modus(make_data, smarttimes_payload):
    """Im Netto-Modus wird keine USt. aufgeschlagen."""
    data = make_data(smarttimes_payload, include_vat=False, grid_zone="wien")
    price = _price_at(data, "2026-06-05T14:00:00+02:00")
    # Netto-Modus: 9,43 + 0,72 + 6,28 = 16,43
    assert data.all_in_value(price) == pytest.approx(16.43)


# --- smartCONTROL (Abwicklungsgebühr 1,2 netto) ---------------------------- #


def test_gesamtpreis_smartcontrol_mit_abwicklungsgebuehr(make_data, smartcontrol_payload):
    """Gesamtpreis mit Abwicklungsgebühr (smartCONTROL) im SNAP-Fenster."""
    data = make_data(
        smartcontrol_payload,
        include_vat=True,
        grid_zone="wien",
        handling_fee_net=1.2,
        tariff_name="smartCONTROL",
    )
    price = _price_at(data, "2026-06-05T14:00:00+02:00")  # gross 3,851, SNAP
    # netto AP = round(3,851/1,2, 4) = 3,2092
    # Nebenkosten netto = 0,72 + 6,28 + 1,2 = 8,20
    # Summe = 11,4092 ; brutto = 11,4092 * 1,2 = 13,69104 -> 13,6910
    assert data.all_in_value(price) == pytest.approx(13.6910)


def test_gesamtpreis_smartcontrol_bei_negativem_preis(make_data, smartcontrol_payload):
    """Auch negative Börsenpreise werden korrekt verrechnet."""
    data = make_data(
        smartcontrol_payload, include_vat=True, grid_zone="wien", handling_fee_net=1.2
    )
    price = _price_at(data, "2026-06-06T12:00:00+02:00")  # gross -0,005, SNAP
    # netto AP = round(-0,005/1,2, 4) = -0,0042
    # + 8,20 = 8,1958 ; brutto = 8,1958 * 1,2 = 9,83496 -> 9,8350
    assert data.all_in_value(price) == pytest.approx(9.8350)


# --- smartNIGHT (aus smartTIMES abgeleitet, keine Abwicklungsgebühr) -------- #
#
# Off-Peak übernimmt die günstigste smartTIMES-Stufe (11,316 brutto = 9,43
# netto), Peak (07:00-23:00) liegt 30 % darüber: 11,316 * 1,3 = 14,7108 brutto
# = 12,259 netto.


def test_gesamtpreis_smartnight_off_peak_ohne_netzgebiet(make_data, smarttimes_payload):
    """Off-Peak-Gesamtpreis ohne Netzgebiet (nur bundesweite Abgaben)."""
    data = make_data(smarttimes_payload, smartnight=True, grid_zone=None)
    price = _price_at(data, "2026-06-05T03:00:00+02:00")  # 3 Uhr -> Off-Peak
    # netto AP 9,43 + Abgaben 0,72 = 10,15 ; brutto = 10,15 * 1,2 = 12,18
    assert data.all_in_value(price) == pytest.approx(12.18)


def test_gesamtpreis_smartnight_peak_ohne_netzgebiet(make_data, smarttimes_payload):
    """Peak-Gesamtpreis ohne Netzgebiet."""
    data = make_data(smarttimes_payload, smartnight=True, grid_zone=None)
    price = _price_at(data, "2026-06-05T08:00:00+02:00")  # 8 Uhr -> Peak
    # netto AP 12,259 + 0,72 = 12,979 ; brutto = 12,979 * 1,2 = 15,5748
    assert data.all_in_value(price) == pytest.approx(15.5748)


def test_gesamtpreis_smartnight_im_snap_fenster_wien(make_data, smarttimes_payload):
    """Das SNAP-Fenster liegt vollständig in der Peak-Zeit und wirkt dort."""
    data = make_data(smarttimes_payload, smartnight=True, grid_zone="wien")
    price = _price_at(data, "2026-06-05T14:00:00+02:00")  # 14 Uhr -> Peak + SNAP
    # netto AP 12,259 + 0,72 + Netz(SNAP) 6,28 = 19,259
    # brutto = 19,259 * 1,2 = 23,1108
    assert data.all_in_value(price) == pytest.approx(23.1108)


def test_peak_aufschlag_trifft_nur_den_arbeitspreis(make_data, smarttimes_payload):
    """Die 30 % gelten dem Arbeitspreis, nicht den Nebenkosten.

    Verglichen werden zwei Zeitpunkte außerhalb des SNAP-Fensters, damit sich
    allein die Tarifzone unterscheidet: 03:00 (Off-Peak) und 18:00 (Peak).
    """
    data = make_data(smarttimes_payload, smartnight=True, grid_zone="wien")
    off_peak = _iso("2026-06-05T03:00:00+02:00")
    peak = _iso("2026-06-05T18:00:00+02:00")

    # Gleiche Nebenkosten zu beiden Zeitpunkten (Abgaben + Netz zur Regelzeit).
    assert data.surcharge_breakdown(off_peak) == pytest.approx(
        data.surcharge_breakdown(peak)
    )
    # Off-Peak: 9,43 + 0,72 + 7,68 = 17,83 ; brutto = 21,396
    # Peak:    12,259 + 0,72 + 7,68 = 20,659 ; brutto = 24,7908
    # Differenz = 3,3948 = 30 % des Off-Peak-Arbeitspreises (11,316 * 0,3).
    assert data.all_in_value(_price_at(data, off_peak.isoformat())) == pytest.approx(
        21.396
    )
    assert data.all_in_value(_price_at(data, peak.isoformat())) == pytest.approx(
        24.7908
    )


def test_aufschluesselung_smartnight_ohne_abwicklungsgebuehr(
    make_data, smarttimes_payload
):
    """smartNIGHT kennt keine Abwicklungsgebühr – sie fehlt in der Aufschlüsselung."""
    data = make_data(smarttimes_payload, smartnight=True, grid_zone="wien")
    breakdown = data.surcharge_breakdown(_iso("2026-06-05T14:00:00+02:00"))
    assert "handling_fee" not in breakdown


# --- Aufschlüsselung & USt.-Konvention ------------------------------------- #


def test_aufschluesselung_smartcontrol(make_data, smartcontrol_payload):
    """Jede Nebenkostenposition wird einzeln brutto ausgewiesen (USt. einmal)."""
    data = make_data(
        smartcontrol_payload, include_vat=True, grid_zone="wien", handling_fee_net=1.2
    )
    moment = _iso("2026-06-05T14:00:00+02:00")  # SNAP
    # Jede Position einzeln brutto (netto * 1,2):
    assert data.surcharge_breakdown(moment) == pytest.approx(
        {
            "electricity_tax": 0.12,    # 0,1  * 1,2
            "renewable_support": 0.744,  # 0,62 * 1,2
            "grid_usage": 6.696,         # 5,58 * 1,2 (SNAP)
            "grid_loss": 0.84,           # 0,700 * 1,2
            "handling_fee": 1.44,        # 1,2  * 1,2  (= 1,44 brutto, vgl. CLAUDE.md)
        }
    )
    # Summe netto (8,20) einmal mit USt.: 8,20 * 1,2 = 9,84
    assert data.surcharges_total(moment) == pytest.approx(9.84)


def test_aufschluesselung_smarttimes_ohne_abwicklungsgebuehr(make_data, smarttimes_payload):
    """Bei smartTIMES taucht keine Abwicklungsgebühr in der Aufschlüsselung auf."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")
    breakdown = data.surcharge_breakdown(_iso("2026-06-05T14:00:00+02:00"))
    assert "handling_fee" not in breakdown


def test_grundgebuehr_brutto_und_netto(make_data, smarttimes_payload):
    """Die Grundgebühr wird je nach Einstellung brutto bzw. netto geliefert."""
    moment = _iso("2026-06-05T12:00:00+02:00")
    gross = make_data(smarttimes_payload, include_vat=True)
    net = make_data(smarttimes_payload, include_vat=False)
    assert gross.basic_fee(moment) == pytest.approx(2.988)  # brutto wie geliefert
    assert net.basic_fee(moment) == pytest.approx(2.49)  # 2,988 / 1,2


# --- Preisrang und Preisquantil -------------------------------------------- #
#
# Bezugsgröße ist der GESAMTPREIS, nicht der Arbeitspreis. Sollwerte von Hand
# aus tests/fixtures/smarttimes.json und den Sätzen oben abgeleitet.
#
# Der 05.06.2026 hat drei Arbeitspreis-Stufen zu je 32 Viertelstunden
# (11,316 | 13,020 | 15,852 brutto ct/kWh). OHNE Netzgebiet bleiben daraus drei
# Gesamtpreis-Stufen – Nebenkosten netto 0,72, also (brutto/1,2 + 0,72) * 1,2:
#     11,316 -> ( 9,43 + 0,72) * 1,2 = 12,180 ct   x 32
#     13,020 -> (10,85 + 0,72) * 1,2 = 13,884 ct   x 32
#     15,852 -> (13,21 + 0,72) * 1,2 = 16,716 ct   x 32
#
# Rang nach der Wettkampfregel "1224" (Gleichstand teilt sich den Rang, die
# nächste Stufe überspringt die verbrauchten Plätze), Quantil als Mittelrang
# (cheaper + equal/2) / count * 100:
#     12,180: cheaper= 0, equal=32 -> Rang  1, ( 0 + 16) / 96 = 16,67 %
#     13,884: cheaper=32, equal=32 -> Rang 33, (32 + 16) / 96 = 50,00 %
#     16,716: cheaper=64, equal=32 -> Rang 65, (64 + 16) / 96 = 83,33 %
STUFEN_OHNE_NETZGEBIET = (
    # (Startzeitpunkt eines Intervalls der Stufe, Rang, Quantil in Prozent)
    ("2026-06-05T12:00:00+02:00", 1, 16.67),   # 11,316 -> 12,180 ct
    ("2026-06-05T00:00:00+02:00", 33, 50.0),   # 13,020 -> 13,884 ct
    ("2026-06-05T18:00:00+02:00", 65, 83.33),  # 15,852 -> 16,716 ct
)


@pytest.mark.parametrize(("start", "rang", "_quantil"), STUFEN_OHNE_NETZGEBIET)
def test_preisrang_gibt_gleich_teuren_intervallen_denselben_rang(
    make_data, smarttimes_payload, start, rang, _quantil
):
    """Alle 32 Intervalle einer Preisstufe tragen denselben Rang.

    Bei einem Zeittarif ist der Gleichstand der Normalfall: Ein Drittel des
    Tages kostet gleich viel. Würde jedes Intervall einen eigenen Platz bekommen,
    hinge der Rang an der Sortierreihenfolge statt am Preis.
    """
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)

    einordnung = data.price_rank(_iso(start))

    assert einordnung is not None
    assert einordnung.rank == rang
    assert einordnung.count == 96
    assert einordnung.equal == 32


@pytest.mark.parametrize(("start", "_rang", "quantil"), STUFEN_OHNE_NETZGEBIET)
def test_quantil_teilt_den_gleichstand_haelftig(
    make_data, smarttimes_payload, start, _rang, quantil
):
    """Der Mittelrang teilt eine preisgleiche Gruppe hälftig.

    Damit bleibt die Skala symmetrisch – die mittlere von drei gleich großen
    Stufen liegt auf genau 50 %. Die naheliegenden Varianten tun das nicht:
    "Anteil kleiner gleich" ergäbe 33,3/66,7/100 %, "Anteil echt kleiner"
    0/33,3/66,7 %.
    """
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)

    assert data.price_rank(_iso(start)).quantile == pytest.approx(quantil)


def test_preisrang_ordnet_nach_gesamtpreis_nicht_nach_arbeitspreis(
    make_data, smarttimes_payload
):
    """Das SNAP-Fenster spaltet eine Arbeitspreis-Stufe in zwei Ränge.

    Mit Netzgebiet Wien hat der 05.06.2026 vier Gesamtpreis-Stufen statt drei,
    weil der Sommer-Nieder-Arbeitspreis (10-16 Uhr) nur einen Teil der
    günstigsten Arbeitspreis-Stufe verbilligt:
        19,716 ct x 24  (11,316 in den SNAP-Stunden 10-15)
        21,396 ct x  8  (11,316 in den Stunden 02-03, regulär)
        23,100 ct x 32  (13,020)
        25,932 ct x 32  (15,852)
    Rang und Quantil daraus:
        19,716: cheaper= 0, equal=24 -> Rang  1, ( 0 + 12) / 96 = 12,50 %
        21,396: cheaper=24, equal= 8 -> Rang 25, (24 +  4) / 96 = 29,17 %

    Nach dem reinen Arbeitspreis wären beide Zeitpunkte nicht zu unterscheiden.
    Der Test hält die festgelegte Bezugsgröße fest: Rutschte die Rechnung
    später auf ``value()`` ab, kämen hier zweimal Rang 1 heraus.
    """
    data = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")

    im_snap = data.price_rank(_iso("2026-06-05T12:00:00+02:00"))
    ausserhalb = data.price_rank(_iso("2026-06-05T02:00:00+02:00"))

    # Gegenprobe: Der Arbeitspreis ist an beiden Zeitpunkten derselbe.
    assert data.value(_price_at(data, "2026-06-05T12:00:00+02:00")) == pytest.approx(
        data.value(_price_at(data, "2026-06-05T02:00:00+02:00"))
    )

    assert (im_snap.rank, im_snap.equal) == (1, 24)
    assert im_snap.quantile == pytest.approx(12.5)
    assert (ausserhalb.rank, ausserhalb.cheaper, ausserhalb.equal) == (25, 24, 8)
    assert ausserhalb.quantile == pytest.approx(29.17)


def test_preisrang_ohne_laufendes_intervall_ist_none(make_data, smarttimes_payload):
    """Ohne Preis für den Zeitpunkt gibt es nichts einzuordnen.

    Die Fixture endet mit dem 06.06.2026. In der Praxis ist das der Zustand
    kurz nach einem Neustart oder nach einem ausgefallenen Abruf – die Sensoren
    stehen dann auf "unbekannt", statt eine Einordnung ohne Grundlage zu melden.
    """
    data = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")

    assert data.price_rank(_iso("2026-06-07T12:00:00+02:00")) is None


def test_preisrang_smartcontrol_ohne_ausgepraegten_gleichstand(
    make_data, smartcontrol_payload
):
    """Gegenprobe mit echten Börsenpreisen statt drei Preisstufen.

    Der 05.06.2026 führt 24 verschiedene Gesamtpreise – je Stunde vier
    preisgleiche Viertelstunden. Um 12:00 Ortszeit (brutto 6,446 ct, vgl.
    tests/test_sensor.py) liegen genau drei Stunden darunter:
        cheaper = 12, equal = 4 -> Rang 13, (12 + 2) / 96 = 14,58 %
    Damit deckt die Suite auch den Fall ab, in dem der Gleichstand klein ist.
    """
    data = make_data(
        smartcontrol_payload, include_vat=True, grid_zone="wien", handling_fee_net=1.2
    )

    einordnung = data.price_rank(_iso("2026-06-05T12:00:00+02:00"))

    assert (einordnung.rank, einordnung.cheaper, einordnung.equal) == (13, 12, 4)
    assert einordnung.count == 96
    assert einordnung.quantile == pytest.approx(14.58)


# --- Sechs Preiszonen: die Rechnung kennt keine Stufenzahl ------------------ #
#
# Die Fixture hat vier Gesamtpreis-Stufen, weil dort das gesamte SNAP-Fenster
# (10-16 Uhr) in der günstigsten Arbeitspreis-Stufe liegt. Der Tarif gibt das
# aber nicht her: Jede der drei Arbeitspreis-Stufen kann innerhalb *und*
# außerhalb des SNAP-Fensters vorkommen, macht bis zu sechs Gesamtpreis-Stufen.
# Welche auftreten, hängt am Zonenplan des Tages – und der kommt je Tag aus der
# API, ist also nichts, worauf sich die Rechnung verlassen darf.
#
# Der Tag hier ist deshalb von Hand gebaut (Muster wie ``_synthetic`` in
# tests/test_cheap_selection.py: für Fälle, die sich in den echten Fixtures
# nicht ergeben). Arbeitspreise wie in der Fixture, Netzgebiet Wien:
#
#   Nebenkosten netto:  SNAP    = 0,72 + 5,58 + 0,700 = 7,00
#                       regulär = 0,72 + 6,98 + 0,700 = 8,40
#   Arbeitspreis netto: Off-Peak 9,43 | Shoulder 10,85 | Peak 13,21
#
#   Off-Peak  SNAP    ( 9,43 + 7,00) * 1,2 = 19,716  x  8 -> Rang  1,  4,17 %
#   Off-Peak  regulär ( 9,43 + 8,40) * 1,2 = 21,396  x 24 -> Rang  9, 20,83 %
#   Shoulder  SNAP    (10,85 + 7,00) * 1,2 = 21,420  x  8 -> Rang 33, 37,50 %
#   Shoulder  regulär (10,85 + 8,40) * 1,2 = 23,100  x 24 -> Rang 41, 54,17 %
#   Peak      SNAP    (13,21 + 7,00) * 1,2 = 24,252  x  8 -> Rang 65, 70,83 %
#   Peak      regulär (13,21 + 8,40) * 1,2 = 25,932  x 24 -> Rang 73, 87,50 %
#
# Quantil jeweils (cheaper + equal/2) / 96 * 100.
OFF_PEAK, SHOULDER, PEAK = 11.316, 13.020, 15.852

# Stundenplan: jede Stufe zweimal im SNAP-Fenster (10-16) und sechsmal außerhalb.
STUNDENPLAN = {
    **dict.fromkeys((10, 11), OFF_PEAK),
    **dict.fromkeys((12, 13), SHOULDER),
    **dict.fromkeys((14, 15), PEAK),
    **dict.fromkeys((0, 1, 2, 3, 16, 17), OFF_PEAK),
    **dict.fromkeys((4, 5, 6, 7, 18, 19), SHOULDER),
    **dict.fromkeys((8, 9, 20, 21, 22, 23), PEAK),
}

# (Stunde eines Intervalls der Zone, Gesamtpreis, Anzahl, Rang, Quantil)
SECHS_ZONEN = (
    (10, 19.716, 8, 1, 4.17),
    (0, 21.396, 24, 9, 20.83),
    (12, 21.420, 8, 33, 37.50),
    (4, 23.100, 24, 41, 54.17),
    (14, 24.252, 8, 65, 70.83),
    (8, 25.932, 24, 73, 87.50),
)


def _sechs_zonen_tag() -> SmartTimesData:
    """Ein 05.06.2026 mit allen sechs Kombinationen aus Stufe und SNAP-Zustand."""
    beginn = datetime(2026, 6, 5, 0, 0, tzinfo=VIENNA)
    prices = []
    for slot in range(96):
        start = beginn + timedelta(minutes=15 * slot)
        prices.append(
            MarketPrice(
                start=start,
                end=start + timedelta(minutes=15),
                gross_ct_per_kwh=STUNDENPLAN[start.hour],
            )
        )
    return SmartTimesData(
        tariff="smartTIMES",
        unit="ct/kWh",
        interval_minutes=15,
        include_vat=True,
        prices=prices,
        grid_zone=get_zone("wien"),
    )


@pytest.mark.parametrize(("stunde", "preis", "anzahl", "rang", "quantil"), SECHS_ZONEN)
def test_preisrang_kommt_mit_sechs_preiszonen_zurecht(
    stunde, preis, anzahl, rang, quantil
):
    """Auch sechs Gesamtpreis-Stufen werden richtig eingeordnet.

    Die Rechnung zählt nur günstigere und gleich teure Intervalle, kennt also
    gar keine Stufenzahl. Dass die Fixture zufällig vier Stufen hat, darf sich
    nirgends festgesetzt haben – ändert smartENERGY den Zonenplan, muss der
    Sensor weiterhin stimmen.
    """
    data = _sechs_zonen_tag()
    zeitpunkt = datetime(2026, 6, 5, stunde, 0, tzinfo=VIENNA)

    einordnung = data.price_rank(zeitpunkt)

    assert data.all_in_value(data.current(zeitpunkt)) == pytest.approx(preis)
    assert einordnung.rank == rang
    assert einordnung.equal == anzahl
    assert einordnung.count == 96
    assert einordnung.quantile == pytest.approx(quantil)


def test_preisrang_trennt_knapp_benachbarte_gesamtpreise():
    """0,024 ct/kWh Unterschied trennen zwei Zonen – und das ist Absicht.

    „Off-Peak außerhalb SNAP“ (21,396) ist in Wien hauchdünn günstiger als
    „Shoulder im SNAP“ (21,420), weil die SNAP-Ersparnis (1,40 netto) die Lücke
    zwischen den Arbeitspreis-Stufen (1,42 netto) fast genau ausgleicht. Ein
    toleranzbehafteter Vergleich würde beide zu einer Zone verschmelzen und
    damit den günstigeren Zeitpunkt verschenken.

    Der Test ist die Gegenprobe zum exakten Float-Vergleich in ``price_rank``:
    Ersetzt man dort ``==`` durch eine Toleranz oberhalb dieser 0,024 ct, fällt
    er (nachgeprüft mit 0,05 – Rang 9 für beide statt 9 und 33). Eine kleinere
    Toleranz träfe ihn nicht, was den Abstand hier zur eigentlichen Zusage
    macht: Er ist die Obergrenze für jede Unschärfe, die sich die Rechnung
    leisten dürfte.
    """
    data = _sechs_zonen_tag()

    guenstiger = data.price_rank(datetime(2026, 6, 5, 0, 0, tzinfo=VIENNA))
    teurer = data.price_rank(datetime(2026, 6, 5, 12, 0, tzinfo=VIENNA))

    abstand = 21.420 - 21.396
    assert abstand == pytest.approx(0.024)
    # Getrennte Ränge, nicht eine gemeinsame Zone.
    assert guenstiger.rank < teurer.rank
    assert guenstiger.equal == 24
    assert teurer.equal == 8


def test_preisrang_gibt_exakt_gleich_teuren_zonen_denselben_rang():
    """Heben sich Stufenlücke und SNAP-Ersparnis exakt auf, zählt eine Zone.

    Die Kehrseite des Tests darüber: Kosten zwei Intervalle wirklich dasselbe,
    gehören sie auf denselben Rang – auch wenn die Summe über verschiedene Wege
    zustande kam (andere Arbeitspreis-Stufe *und* anderer SNAP-Zustand). Genau
    deshalb trägt die Rundung auf vier Nachkommastellen den Vergleich und nicht
    die Gleichheit des Rechenwegs.

    Bei keinem der 14 echten Netzgebiete fallen die Werte heute exakt zusammen
    (Wien kommt mit 0,02 netto am nächsten), deshalb hier ein eigens gebautes.
    """
    # Netto-Lücke Off-Peak -> Shoulder: 10,85 - 9,43 = 1,42
    zone = GridZone("test", "Testgebiet", usage_ap=7.00, usage_snap=5.58, loss=0.700)
    assert round(zone.usage_ap - zone.usage_snap, 4) == pytest.approx(1.42)

    beginn = datetime(2026, 6, 5, 0, 0, tzinfo=VIENNA)
    mach = lambda stunde, brutto: MarketPrice(  # noqa: E731
        start=beginn.replace(hour=stunde),
        end=beginn.replace(hour=stunde) + timedelta(minutes=15),
        gross_ct_per_kwh=brutto,
    )
    # 12 Uhr: SNAP aktiv, teurere Stufe. 20 Uhr: kein SNAP, günstigere Stufe.
    shoulder_im_snap = mach(12, SHOULDER)
    off_peak_regulaer = mach(20, OFF_PEAK)
    data = SmartTimesData(
        tariff="smartTIMES",
        unit="ct/kWh",
        interval_minutes=15,
        include_vat=True,
        prices=[shoulder_im_snap, off_peak_regulaer],
        grid_zone=zone,
    )

    # (10,85 + 0,72 + 5,58 + 0,700) * 1,2 = (9,43 + 0,72 + 7,00 + 0,700) * 1,2
    assert data.all_in_value(shoulder_im_snap) == pytest.approx(21.42)
    assert data.all_in_value(off_peak_regulaer) == pytest.approx(21.42)

    for zeitpunkt in (shoulder_im_snap.start, off_peak_regulaer.start):
        einordnung = data.price_rank(zeitpunkt)
        assert einordnung.rank == 1
        assert einordnung.equal == 2
        assert einordnung.quantile == pytest.approx(50.0)


# --- Semantik der Quantil-Skala --------------------------------------------- #
#
# Diese beiden Zusagen standen zunaechst nur in der Doku – und zwei davon falsch
# ("0 % = guenstigstes Intervall", "unter 25 % = guenstigstes Viertel").
# Deshalb hier als geprueftes Verhalten.
#
# Herleitung des Tagesmittels von Hand: Bei lauter verschiedenen Preisen traegt
# das Intervall auf sortierter Position i (ab 0) den Wert (i + 0,5) / n. Die
# Summe ist  SUM(i + 0,5) / n = (n(n-1)/2 + n/2) / n = n/2 ,  das Mittel also
# genau 0,5. Ein Gleichstand aendert daran nichts: Eine Gruppe der Groesse e mit
# c guenstigeren traegt e * (c + e/2) / n bei – genau so viel wie dieselben e
# Intervalle auf den Einzelpositionen c .. c+e-1. Der Mittelrang verschiebt also
# nur innerhalb der Gruppe, nie die Summe. Das ist die eigentliche Zusage der
# Methode; "Anteil <=" bzw. "Anteil <" verschoeben das Mittel um eine halbe
# Gleichstandsbreite nach oben bzw. unten.


@pytest.mark.parametrize(
    ("payload_name", "grid_zone", "handling_fee_net"),
    [
        ("smarttimes_payload", None, 0.0),
        ("smarttimes_payload", "wien", 0.0),
        ("smartcontrol_payload", "wien", 1.2),
    ],
)
def test_quantil_liegt_im_tagesmittel_bei_genau_50_prozent(
    request, make_data, payload_name, grid_zone, handling_fee_net
):
    """Der Mittelrang haelt die Skala symmetrisch – unabhaengig vom Gleichstand.

    Genau das ist der Grund fuer die Methode, nicht etwa das Erreichen der
    Endpunkte (siehe den Test darunter). Geprueft ueber drei sehr verschiedene
    Verteilungen: drei Stufen, vier Stufen, 24 Stufen.
    """
    data = make_data(
        request.getfixturevalue(payload_name),
        include_vat=True,
        grid_zone=grid_zone,
        handling_fee_net=handling_fee_net,
    )
    tag = _tagesintervalle(data)

    quantile = [data.price_rank(p.start).quantile for p in tag]

    assert len(quantile) == 96
    # Toleranz nur wegen der Rundung auf QUANTILE_DECIMALS = 2 Stellen.
    assert sum(quantile) / len(quantile) == pytest.approx(50.0, abs=0.01)


def test_quantil_erreicht_0_und_100_prozent_nie(make_data, smarttimes_payload):
    """Die Endpunkte kommen nicht vor – und Schwellen greifen entsprechend weit.

    Das guenstigste Preisniveau liegt bei der halben Breite seiner
    Gleichstandsgruppe. Bei smartTIMES ohne Netzgebiet sind das drei Stufen zu
    je 32 Viertelstunden, also (0 + 16) / 96 = 16,67 % – nicht 0 %.

    Praktische Folge, die in der Doku zunaechst falsch stand: Eine Schwelle
    waehlt nicht den gleich grossen Anteil des Tages. Preisgleiche Intervalle
    tragen denselben Wert und kommen deshalb nur gemeinsam unter die Schwelle;
    "unter 25 %" trifft hier die ganze guenstigste Stufe und damit 32 von 96
    Intervallen – ein Drittel des Tages, nicht ein Viertel.
    """
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    tag = _tagesintervalle(data)

    quantile = [data.price_rank(p.start).quantile for p in tag]

    assert min(quantile) == pytest.approx(16.67)
    assert max(quantile) == pytest.approx(83.33)
    assert min(quantile) > 0.0 and max(quantile) < 100.0

    assert sum(1 for q in quantile if q < 25) == 32
