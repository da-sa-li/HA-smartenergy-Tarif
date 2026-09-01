"""Tests für die Ableitung des smartNIGHT-Tarifs aus der smartTIMES-Antwort.

smartNIGHT hat keinen eigenen Endpunkt: Peak ist 07:00–23:00 Uhr Ortszeit,
Off-Peak die übrige Zeit, der Off-Peak-Arbeitspreis ist der von smartTIMES und
der Peak-Preis liegt 30 % darüber (siehe ``custom_components/smartenergy/
smartnight.py``).

Die Sollwerte unten sind **von Hand** aus dieser Regel und der eingecheckten
Fixture abgeleitet, nicht aus dem geprüften Code erzeugt. Grundlage ist die
Fixture ``smarttimes.json`` (05./06.06.2026, Europe/Vienna):

* Preisstufen der Fixture: 11,316 / 13,02 / 15,852 ct/kWh brutto.
* Off-Peak-Niveau = günstigste Stufe des Tages = **11,316** ct/kWh.
* Peak = 11,316 × 1,3 = **14,7108** ct/kWh.
* Je Kalendertag 32 Off-Peak-Intervalle (00:00–07:00 und 23:00–24:00) und
  64 Peak-Intervalle (07:00–23:00); zusammen die 96 Viertelstunden eines Tages.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.const import (
    API_URL,
    TARIFF_API_URLS,
    TARIFF_SMARTNIGHT,
)
from custom_components.smartenergy.smartnight import (
    SMARTNIGHT_PEAK_FACTOR,
    SmartNightApiClient,
    als_smartnight,
    ist_peak,
)
from tests.conftest import VIENNA

# Sollwerte laut Spezifikation (siehe Modul-Docstring).
OFF_PEAK_BRUTTO = 11.316
PEAK_BRUTTO = 14.7108
OFF_PEAK_INTERVALLE_JE_TAG = 32
PEAK_INTERVALLE_JE_TAG = 64


def _bauwerte(start_utc: datetime, anzahl: int, wert: float) -> list[dict]:
    """Baut ``anzahl`` Viertelstunden-Einträge ab ``start_utc`` mit ``wert``.

    Gerechnet wird in UTC und erst zum Schluss nach Europe/Vienna umgerechnet:
    Ein ``timedelta`` auf einen zeitzonenbehafteten Zeitstempel addiert sonst
    auf der Wanduhr und überspringt die Umstellungsstunde nicht.
    """
    return [
        {
            "dateTimeFrom": (start_utc + timedelta(minutes=15 * i))
            .astimezone(VIENNA)
            .isoformat(),
            "value": wert,
        }
        for i in range(anzahl)
    ]


def _antwort(werte: list[dict]) -> dict:
    """Verpackt Preiswerte in eine smartTIMES-Antwort (verschachteltes Format)."""
    return {"energyPrice": {"interval": 15, "unit": "cent/kWh", "values": werte}}


@pytest.mark.parametrize(
    ("stunde", "minute", "erwartet"),
    [
        (0, 0, False),    # tiefe Nacht
        (6, 45, False),   # letzte Viertelstunde vor dem Peak-Fenster
        (7, 0, True),     # Beginn des Peak-Fensters (einschließlich)
        (12, 30, True),   # Mitte des Peak-Fensters
        (22, 45, True),   # letzte Viertelstunde des Peak-Fensters
        (23, 0, False),   # Ende des Peak-Fensters (ausschließlich)
        (23, 45, False),  # letzte Viertelstunde des Tages
    ],
)
def test_peak_fenster_reicht_von_sieben_bis_dreiundzwanzig(
    stunde: int, minute: int, erwartet: bool
):
    """Das Peak-Fenster umfasst [07:00, 23:00) Uhr Ortszeit."""
    moment = datetime(2026, 6, 5, stunde, minute, tzinfo=VIENNA)

    assert ist_peak(moment) is erwartet


def test_peak_aufschlag_betraegt_dreissig_prozent():
    """Der Faktor ist der in der Tarifbeschreibung genannte Aufschlag von 30 %."""
    assert SMARTNIGHT_PEAK_FACTOR == 1.30


def test_smartnight_ruft_den_smarttimes_endpunkt_ab():
    """Ohne eigenen Endpunkt entsteht smartNIGHT aus der smartTIMES-Antwort."""
    assert TARIFF_API_URLS[TARIFF_SMARTNIGHT] == API_URL


def test_off_peak_preis_ist_das_tagesminimum_von_smarttimes(smarttimes_payload):
    """Off-Peak übernimmt die günstigste Preisstufe des Tages: 11,316 ct/kWh."""
    abgeleitet = als_smartnight(SmartTimesApiClient._parse(smarttimes_payload))

    off_peak = [p for p in abgeleitet.prices if not ist_peak(p.start)]
    assert {p.gross_ct_per_kwh for p in off_peak} == {OFF_PEAK_BRUTTO}


def test_peak_preis_liegt_dreissig_prozent_ueber_off_peak(smarttimes_payload):
    """Peak kostet 11,316 × 1,3 = 14,7108 ct/kWh brutto."""
    abgeleitet = als_smartnight(SmartTimesApiClient._parse(smarttimes_payload))

    peak = [p for p in abgeleitet.prices if ist_peak(p.start)]
    assert {p.gross_ct_per_kwh for p in peak} == {PEAK_BRUTTO}


def test_der_tarif_kennt_genau_zwei_preisstufen(smarttimes_payload):
    """Aus den drei Stufen von smartTIMES werden die zwei von smartNIGHT."""
    ausgang = SmartTimesApiClient._parse(smarttimes_payload)
    abgeleitet = als_smartnight(ausgang)

    assert len({p.gross_ct_per_kwh for p in ausgang.prices}) == 3
    assert {p.gross_ct_per_kwh for p in abgeleitet.prices} == {
        OFF_PEAK_BRUTTO,
        PEAK_BRUTTO,
    }


def test_je_tag_zweiunddreissig_off_peak_und_vierundsechzig_peak_intervalle(
    smarttimes_payload,
):
    """Off-Peak sind 8 Stunden (23:00–07:00), Peak die übrigen 16."""
    abgeleitet = als_smartnight(SmartTimesApiClient._parse(smarttimes_payload))

    for tag in (date(2026, 6, 5), date(2026, 6, 6)):
        tagespreise = [
            p for p in abgeleitet.prices if dt_util.as_local(p.start).date() == tag
        ]
        peak = [p for p in tagespreise if ist_peak(p.start)]
        assert len(tagespreise) == 96
        assert len(peak) == PEAK_INTERVALLE_JE_TAG
        assert len(tagespreise) - len(peak) == OFF_PEAK_INTERVALLE_JE_TAG


def test_ableitung_reicht_raster_einheit_und_grundgebuehr_durch(smarttimes_payload):
    """Nur die Preise ändern sich – Raster, Einheit und Grundgebühr bleiben.

    Die Grundgebühr ist bei smartNIGHT dieselbe wie bei den übrigen Tarifen; sie
    kommt aus demselben ``basicFee``-Block der Antwort (Fixture: 2,988 EUR/Monat
    brutto).
    """
    ausgang = SmartTimesApiClient._parse(smarttimes_payload)
    abgeleitet = als_smartnight(ausgang)

    assert abgeleitet.interval_minutes == 15
    assert abgeleitet.unit == "cent/kWh"
    assert abgeleitet.basic_fee_unit == "EUR/month"
    assert [f.gross_value for f in abgeleitet.basic_fees] == [2.988, 2.988]
    assert [(p.start, p.end) for p in abgeleitet.prices] == [
        (p.start, p.end) for p in ausgang.prices
    ]


def test_ableitung_weist_den_tarif_als_smartnight_aus(smarttimes_payload):
    """Das Ergebnis nennt smartNIGHT, nicht den abgerufenen smartTIMES-Tarif."""
    ausgang = SmartTimesApiClient._parse(smarttimes_payload)
    abgeleitet = als_smartnight(ausgang)

    assert ausgang.tariff == "smartTIMES"
    assert abgeleitet.tariff == "smartNIGHT"


def test_ableitung_laesst_das_preisraster_lueckenlos(smarttimes_payload):
    """Ende eines Intervalls = Beginn des nächsten.

    Darauf baut die Blocksuche ``SmartTimesData._consecutive_selection``: Sie
    erkennt einen zusammenhängenden Lauf genau daran.
    """
    abgeleitet = als_smartnight(SmartTimesApiClient._parse(smarttimes_payload))

    for vorher, nachher in zip(
        abgeleitet.prices, abgeleitet.prices[1:], strict=False
    ):
        assert vorher.end == nachher.start


def test_jeder_tag_bekommt_sein_eigenes_off_peak_niveau():
    """Ein Preiswechsel zwischen heute und morgen wird je Tag übernommen.

    Von Hand gebaute Antwort: Am 05.06. ist der günstigste Preis 10,0, am 06.06.
    dagegen 15,0 ct/kWh brutto. Erwartet werden daraus die Peak-Preise
    10,0 × 1,3 = 13,0 bzw. 15,0 × 1,3 = 19,5 – ein über beide Tage gebildetes
    Minimum ergäbe stattdessen überall 10,0 bzw. 13,0.
    """
    # 05.06.2026 00:00 Ortszeit (Sommerzeit, +02:00) = 04.06. 22:00 UTC.
    tag_eins = datetime(2026, 6, 4, 22, 0, tzinfo=UTC)
    tag_zwei = tag_eins + timedelta(days=1)
    werte = [
        # Tag 1: durchweg 20,0 – bis auf eine Viertelstunde um 03:00 mit 10,0.
        *_bauwerte(tag_eins, 12, 20.0),
        *_bauwerte(tag_eins + timedelta(hours=3), 1, 10.0),
        *_bauwerte(tag_eins + timedelta(hours=3, minutes=15), 83, 20.0),
        # Tag 2: durchweg 30,0 – bis auf eine Viertelstunde um 03:00 mit 15,0.
        *_bauwerte(tag_zwei, 12, 30.0),
        *_bauwerte(tag_zwei + timedelta(hours=3), 1, 15.0),
        *_bauwerte(tag_zwei + timedelta(hours=3, minutes=15), 83, 30.0),
    ]

    abgeleitet = als_smartnight(SmartTimesApiClient._parse(_antwort(werte)))

    stufen = {
        (dt_util.as_local(p.start).date(), ist_peak(p.start)): p.gross_ct_per_kwh
        for p in abgeleitet.prices
    }
    assert stufen == {
        (date(2026, 6, 5), False): 10.0,
        (date(2026, 6, 5), True): 13.0,
        (date(2026, 6, 6), False): 15.0,
        (date(2026, 6, 6), True): 19.5,
    }


def test_zeitumstellung_verschiebt_das_peak_fenster_nicht():
    """Am Tag des Sommerzeit-Beginns gilt weiterhin die Wanduhr.

    Am 29.03.2026 springt Europe/Vienna um 02:00 auf 03:00 – der Kalendertag hat
    nur 23 Stunden bzw. 92 Viertelstunden. Das Peak-Fenster 07:00–23:00 liegt
    vollständig nach dem Sprung und umfasst deshalb unverändert 64 Intervalle;
    die restlichen 28 sind Off-Peak (00:00–02:00 und 03:00–07:00 machen zusammen
    24 Viertelstunden, dazu 23:00–24:00 mit vieren).

    Eine Regel über „Sekunden seit Tagesbeginn“ statt über die lokale Stunde
    hätte das Fenster an diesem Tag um eine Stunde verschoben.
    """
    # 29.03.2026 00:00 Ortszeit (noch Winterzeit, +01:00) = 28.03. 23:00 UTC.
    start = datetime(2026, 3, 28, 23, 0, tzinfo=UTC)

    abgeleitet = als_smartnight(SmartTimesApiClient._parse(_antwort(_bauwerte(start, 92, 20.0))))

    peak = [p for p in abgeleitet.prices if ist_peak(p.start)]
    assert len(abgeleitet.prices) == 92
    assert len(peak) == PEAK_INTERVALLE_JE_TAG
    assert len(abgeleitet.prices) - len(peak) == 28
    # 20,0 × 1,3 = 26,0 ct/kWh brutto.
    assert {p.gross_ct_per_kwh for p in peak} == {26.0}


async def test_client_leitet_die_abgerufene_antwort_ab(smarttimes_payload):
    """``SmartNightApiClient`` rechnet die geerbte smartTIMES-Antwort um.

    Gepatcht wird die Basisklasse: Genau ihren Abruf – samt User-Agent, Zeitlimit
    und Fehlerbehandlung – erbt der smartNIGHT-Client unverändert.
    """
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    client = SmartNightApiClient(None, API_URL)

    with patch.object(
        SmartTimesApiClient, "async_get_prices", AsyncMock(return_value=parsed)
    ):
        ergebnis = await client.async_get_prices()

    assert ergebnis.tariff == "smartNIGHT"
    assert {p.gross_ct_per_kwh for p in ergebnis.prices} == {
        OFF_PEAK_BRUTTO,
        PEAK_BRUTTO,
    }
