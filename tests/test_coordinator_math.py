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

from datetime import datetime

import pytest

from custom_components.smartenergy.api import MarketPrice
from custom_components.smartenergy.coordinator import SmartTimesData


def _iso(value: str) -> datetime:
    """Kurzschreibweise für ein ISO-8601-datetime (mit Offset)."""
    return datetime.fromisoformat(value)


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
