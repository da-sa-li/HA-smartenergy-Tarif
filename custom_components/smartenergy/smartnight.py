"""Tarifregeln für smartNIGHT – abgeleitet aus der smartTIMES-Antwort.

smartNIGHT ist ein Zwei-Zonen-Tarif: **Peak** von 07:00 bis 23:00 Uhr Ortszeit,
**Off-Peak** die übrige Zeit. Der Off-Peak-Arbeitspreis ist derselbe wie bei
smartTIMES, der Peak-Preis liegt 30 % darüber. Betroffen ist ausschließlich der
**Arbeitspreis** – Abgaben und Netzentgelte (samt SNAP) gelten unverändert und
werden wie bei allen Tarifen im Koordinator aufgeschlagen.

**Eine eigene API gibt es für smartNIGHT nicht.** Da sein Off-Peak-Preis
definitionsgemäß der von smartTIMES ist, wird der Tarif aus der
smartTIMES-Antwort *berechnet* statt fest hinterlegt. Das hat zwei Vorteile,
die eine Konstante im Code nicht hätte: Der Preis folgt der monatlichen
Anpassung von smartENERGY automatisch, und Viertelstundenraster, Grundgebühr,
Morgen-Preise, Cache, Drosselung, Retry und Diagnose bleiben Wort für Wort
dieselben wie bei smartTIMES – es entsteht kein zweiter, andersartiger
Datenpfad, der eigene Fehler mitbrächte.

Der Einstiegspunkt ist :class:`SmartNightApiClient`: Er erbt den kompletten
HTTP-Pfad von :class:`~.api.SmartTimesApiClient` und legt allein die Umrechnung
darüber. Der Koordinator ruft ohnehin nur ``async_get_prices()`` auf und merkt
von dem Unterschied nichts.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Final

from homeassistant.util import dt as dt_util

from .api import MarketPrice, SmartTimesApiClient, SmartTimesResult
from .const import TARIFF_DISPLAY_NAMES, TARIFF_SMARTNIGHT

# Peak-Fenster: täglich 07:00–23:00 Uhr Ortszeit, inkl. Wochenende. Maßgeblich
# ist – wie beim SNAP-Fenster in `grid_fees.py` – der **Beginn** des jeweiligen
# 15-Minuten-Intervalls.
SMARTNIGHT_PEAK_START_HOUR: Final = 7
SMARTNIGHT_PEAK_END_HOUR: Final = 23

# Aufschlag auf den Off-Peak-Arbeitspreis während der Peak-Zeit: +30 %.
#
# Ob der Faktor auf den Brutto- oder den Nettopreis wirkt, ist rechnerisch
# einerlei – die USt. ist proportional, 1,2 * 1,3 = 1,3 * 1,2. Angewendet wird
# er hier auf den Bruttopreis, weil die API in dieser Größe liefert und
# `MarketPrice` sie so speichert (siehe api.py).
SMARTNIGHT_PEAK_FACTOR: Final = 1.30


def ist_peak(moment: datetime) -> bool:
    """Ob ``moment`` in der Peak-Zeit (07:00–23:00 Ortszeit) liegt.

    Bewusst über die *lokale* Stunde und nicht über eine feste Zahl Sekunden
    seit Tagesbeginn: An den Umstellungstagen der Sommerzeit ist ein Kalendertag
    23 bzw. 25 Stunden lang. Der Tarif nennt Wanduhrzeiten, also entscheidet die
    Wanduhr – genauso hält es ``grid_fees.is_snap`` für das SNAP-Fenster.
    """
    local = dt_util.as_local(moment)
    return SMARTNIGHT_PEAK_START_HOUR <= local.hour < SMARTNIGHT_PEAK_END_HOUR


def _off_peak_je_tag(prices: list[MarketPrice]) -> dict[date, float]:
    """Off-Peak-Bruttopreis (ct/kWh) je lokalem Kalendertag.

    Das Off-Peak-Niveau ist der **günstigste Preis des Tages** in der
    smartTIMES-Antwort. Bewusst das Minimum statt der fest verdrahteten
    smartTIMES-Fenster (derzeit 02:00–04:00 und 10:00–16:00): Verschiebt
    smartENERGY seine Zonen, bleibt die Regel richtig; eine nachgebaute
    Fenstertabelle wäre ab diesem Tag still falsch.

    Je Kalendertag getrennt, weil eine Antwort zwei Tage umfasst und ein
    Preiswechsel genau dazwischen liegen kann – dann gilt für morgen bereits das
    neue Niveau, während heute noch das alte läuft.
    """
    niveau: dict[date, float] = {}
    for price in prices:
        tag = dt_util.as_local(price.start).date()
        bisher = niveau.get(tag)
        if bisher is None or price.gross_ct_per_kwh < bisher:
            niveau[tag] = price.gross_ct_per_kwh
    return niveau


def als_smartnight(result: SmartTimesResult) -> SmartTimesResult:
    """Rechnet eine smartTIMES-Antwort in den smartNIGHT-Tarif um.

    Jedes Intervall behält seinen Zeitraum und bekommt den Preis seiner
    smartNIGHT-Zone: Off-Peak den Tagesminimalpreis (siehe
    :func:`_off_peak_je_tag`), Peak denselben Wert zuzüglich
    ``SMARTNIGHT_PEAK_FACTOR``.

    Alles Übrige wird unverändert durchgereicht – Raster, Einheit und der
    ``basicFee``-Block, dessen Grundgebühr bei smartNIGHT dieselbe ist wie bei
    den anderen Tarifen. Lediglich ``tariff`` wird auf den Anzeigenamen des
    Tarifs gesetzt, damit das Ergebnis nicht fälschlich smartTIMES ausweist (der
    Koordinator zieht den Anzeigenamen ohnehin aus der Nutzerauswahl, siehe
    ``coordinator._async_update_data``).

    Gerundet wird auf vier Nachkommastellen – dieselbe Genauigkeit, mit der
    ``api.py`` die gelieferten Preise ablegt. Daran hängt der exakte
    Preisvergleich in ``SmartTimesData.price_rank``.
    """
    niveau = _off_peak_je_tag(result.prices)
    prices: list[MarketPrice] = []
    for price in result.prices:
        off_peak = niveau[dt_util.as_local(price.start).date()]
        brutto = (
            round(off_peak * SMARTNIGHT_PEAK_FACTOR, 4)
            if ist_peak(price.start)
            else off_peak
        )
        prices.append(replace(price, gross_ct_per_kwh=brutto))
    return replace(
        result,
        tariff=TARIFF_DISPLAY_NAMES[TARIFF_SMARTNIGHT],
        prices=prices,
    )


class SmartNightApiClient(SmartTimesApiClient):
    """Liefert smartNIGHT-Preise, abgerufen über die smartTIMES-API.

    Erbt den gesamten HTTP-Pfad – User-Agent, Zeitlimit, Fehlerklassen, Parser –
    und legt allein die Umrechnung darüber. Damit gilt für smartNIGHT jede
    Zusage, die für smartTIMES gilt, ohne sie ein zweites Mal zu schreiben.
    """

    async def async_get_prices(self) -> SmartTimesResult:
        """Ruft die smartTIMES-Preise ab und rechnet sie in smartNIGHT um."""
        return als_smartnight(await super().async_get_prices())
