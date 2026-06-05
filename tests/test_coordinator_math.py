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

from custom_components.smartenergy.coordinator import SmartTimesData


def _iso(value: str) -> datetime:
    """Kurzschreibweise für ein ISO-8601-datetime (mit Offset)."""
    return datetime.fromisoformat(value)


def _price_at(data: SmartTimesData, value: str):
    """Liefert den Preis-Eintrag mit dem Startzeitpunkt ``value``."""
    target = _iso(value)
    for price in data.prices:
        if price.start == target:
            return price
    raise AssertionError(f"kein Intervall mit Start {value}")


# --- smartTIMES (keine Abwicklungsgebühr) ---------------------------------- #


def test_allin_smarttimes_snap_wien(make_data, smarttimes_payload):
    """Gesamtpreis im SNAP-Fenster mit Netzgebiet Wien (brutto)."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")
    price = _price_at(data, "2026-06-05T14:00:00+02:00")  # 14 Uhr -> SNAP aktiv
    # netto AP 11,316/1,2 = 9,43 ; + Abgaben 0,72 + Netz(SNAP) 6,28 = 16,43
    # brutto = 16,43 * 1,2 = 19,716
    assert data.all_in_value(price) == pytest.approx(19.716)


def test_allin_smarttimes_non_snap_wien(make_data, smarttimes_payload):
    """Gesamtpreis außerhalb des SNAP-Fensters (Regel-Netzentgelt)."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")
    price = _price_at(data, "2026-06-05T18:00:00+02:00")  # 18 Uhr -> kein SNAP
    # netto AP 15,852/1,2 = 13,21 ; + 0,72 + Netz(Regel) 7,68 = 21,61
    # brutto = 21,61 * 1,2 = 25,932
    assert data.all_in_value(price) == pytest.approx(25.932)


def test_allin_smarttimes_without_grid_zone(make_data, smarttimes_payload):
    """Ohne Netzgebiet fließen nur die bundesweiten Abgaben ein."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone=None)
    price = _price_at(data, "2026-06-05T14:00:00+02:00")
    # netto 9,43 + 0,72 = 10,15 ; brutto = 12,18
    assert data.all_in_value(price) == pytest.approx(12.18)


def test_allin_net_mode(make_data, smarttimes_payload):
    """Im Netto-Modus wird keine USt. aufgeschlagen."""
    data = make_data(smarttimes_payload, include_vat=False, grid_zone="wien")
    price = _price_at(data, "2026-06-05T14:00:00+02:00")
    # Netto-Modus: 9,43 + 0,72 + 6,28 = 16,43
    assert data.all_in_value(price) == pytest.approx(16.43)


# --- smartCONTROL (Abwicklungsgebühr 1,2 netto) ---------------------------- #


def test_allin_smartcontrol_with_handling_fee(make_data, smartcontrol_payload):
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


def test_allin_smartcontrol_negative_price(make_data, smartcontrol_payload):
    """Auch negative Börsenpreise werden korrekt verrechnet."""
    data = make_data(
        smartcontrol_payload, include_vat=True, grid_zone="wien", handling_fee_net=1.2
    )
    price = _price_at(data, "2026-06-06T12:00:00+02:00")  # gross -0,005, SNAP
    # netto AP = round(-0,005/1,2, 4) = -0,0042
    # + 8,20 = 8,1958 ; brutto = 8,1958 * 1,2 = 9,83496 -> 9,8350
    assert data.all_in_value(price) == pytest.approx(9.8350)


# --- Aufschlüsselung & USt.-Konvention ------------------------------------- #


def test_breakdown_smartcontrol(make_data, smartcontrol_payload):
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


def test_breakdown_smarttimes_has_no_handling_fee(make_data, smarttimes_payload):
    """Bei smartTIMES taucht keine Abwicklungsgebühr in der Aufschlüsselung auf."""
    data = make_data(smarttimes_payload, include_vat=True, grid_zone="wien")
    breakdown = data.surcharge_breakdown(_iso("2026-06-05T14:00:00+02:00"))
    assert "handling_fee" not in breakdown


def test_basic_fee_gross_and_net(make_data, smarttimes_payload):
    """Die Grundgebühr wird je nach Einstellung brutto bzw. netto geliefert."""
    moment = _iso("2026-06-05T12:00:00+02:00")
    gross = make_data(smarttimes_payload, include_vat=True)
    net = make_data(smarttimes_payload, include_vat=False)
    assert gross.basic_fee(moment) == 2.988            # brutto wie geliefert
    assert net.basic_fee(moment) == pytest.approx(2.49)  # 2,988 / 1,2
