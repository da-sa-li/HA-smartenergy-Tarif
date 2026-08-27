"""Tests des API-Parsers für beide Antwortformate (smartTIMES & smartCONTROL).

Die erwarteten Preis-/Gebührenwerte sind die jeweils ersten Einträge der echten
API-Fixtures in ``tests/fixtures/`` – sie werden hier direkt gegen die Fixture
geprüft (nicht aus dem Parser-Code erzeugt) und im Kommentar mit ihrer Herkunft
dokumentiert.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from multidict import CIMultiDict

from custom_components.smartenergy.api import (
    MarketPrice,
    SmartTimesApiClient,
    SmartTimesApiError,
    SmartTimesApiPayloadError,
    SmartTimesApiPermanentError,
    SmartTimesApiTimeoutError,
    _build_user_agent,
    _parse_retry_after,
)


def _iso(value: str) -> datetime:
    """Kurzschreibweise für ein ISO-8601-datetime (mit Offset)."""
    return datetime.fromisoformat(value)


def test_parst_das_smarttimes_format(smarttimes_payload):
    """Das verschachtelte ``energyPrice``-Format wird vollständig ausgewertet."""
    result = SmartTimesApiClient._parse(smarttimes_payload)
    assert result.interval_minutes == 15
    assert result.unit == "cent/kWh"
    # Kein "tariff"-Feld im Payload -> dokumentierter Fallback.
    assert result.tariff == "smartTIMES"
    assert len(result.prices) == 192  # zwei Tage je 96 Viertelstunden
    # Chronologisch sortiert.
    assert result.prices == sorted(result.prices, key=lambda p: p.start)
    first = result.prices[0]
    # Erster Eintrag aus tests/fixtures/smarttimes.json (energyPrice.values[0]):
    # dateTimeFrom 2026-06-05T00:00:00+02:00, value 13.020.
    assert first.gross_ct_per_kwh == 13.020
    assert first.start == _iso("2026-06-05T00:00:00+02:00")
    assert first.end == _iso("2026-06-05T00:15:00+02:00")  # +15 min (interval)
    # Grundgebühr-Block (basicFee) wird ausgelesen.
    assert result.basic_fee_unit == "EUR/month"
    # Erster basicFee-Eintrag aus der Fixture (basicFee.values[0].value = 2.988).
    assert result.basic_fees[0].gross_value == 2.988


def test_parst_das_smartcontrol_format(smartcontrol_payload):
    """Das flache ``data``-Format (mit Offset) wird als Fallback ausgewertet."""
    result = SmartTimesApiClient._parse(smartcontrol_payload)
    assert result.interval_minutes == 15
    assert result.unit == "ct/kWh"
    assert result.tariff == "EPEXSPOTAT"
    assert len(result.prices) == 192
    # Erster Eintrag aus tests/fixtures/smartcontrol.json (data[0]):
    # date 2026-06-05T00:00:00+02:00, value 10.942.
    assert result.prices[0].gross_ct_per_kwh == 10.942
    assert result.prices[0].start == _iso("2026-06-05T00:00:00+02:00")
    # Kein basicFee-Block in dieser Antwort.
    assert result.basic_fees == []
    assert result.basic_fee_unit is None


def test_marktpreis_brutto_und_netto():
    """Brutto/Netto-Umrechnung: 13,020 brutto / 1,2 = 10,85 netto."""
    price = MarketPrice(
        start=_iso("2026-06-05T00:00:00+02:00"),
        end=_iso("2026-06-05T00:15:00+02:00"),
        gross_ct_per_kwh=13.020,
    )
    assert price.net_ct_per_kwh == 10.85
    assert price.price(include_vat=True) == 13.020
    assert price.price(include_vat=False) == 10.85


def test_datum_behaelt_vorhandenen_offset():
    """Ein vorhandener Zeitzonen-Offset bleibt erhalten (+02:00)."""
    parsed = SmartTimesApiClient._parse_date("2026-06-05T14:00:00+02:00")
    assert parsed.utcoffset().total_seconds() == 2 * 3600


def test_datum_ohne_offset_nimmt_die_standardzeitzone():
    """Ohne Offset wird die Standard-Zeitzone (Europe/Vienna) angenommen."""
    parsed = SmartTimesApiClient._parse_date("2026-06-05T14:00:00")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 2 * 3600


def test_parser_weist_ein_nicht_objekt_zurueck():
    """Ein nicht-Objekt als Antwort löst einen Payload-Fehler aus."""
    with pytest.raises(SmartTimesApiPayloadError):
        SmartTimesApiClient._parse([])


def test_parser_weist_eine_leere_werteliste_zurueck():
    """Eine leere Werteliste löst einen Payload-Fehler aus (keine Preisdaten)."""
    with pytest.raises(SmartTimesApiPayloadError):
        SmartTimesApiClient._parse({"energyPrice": {"values": []}})


def test_parser_weist_durchweg_ungueltige_eintraege_zurueck():
    """Sind alle Einträge unbrauchbar (kein Datum/Wert), bleibt kein Preis übrig."""
    with pytest.raises(SmartTimesApiPayloadError):
        SmartTimesApiClient._parse({"energyPrice": {"values": [{"foo": "bar"}]}})


def test_fehlerarten_sind_geschwister_und_keine_unterklassen():
    """Timeout- und Payload-Fehler hängen NICHT unter ``SmartTimesApiPermanentError``
    und umgekehrt – sonst schlüge der isinstance-Check in coordinator.py an.
    """
    assert issubclass(SmartTimesApiTimeoutError, SmartTimesApiError)
    assert issubclass(SmartTimesApiPayloadError, SmartTimesApiError)
    assert not issubclass(SmartTimesApiTimeoutError, SmartTimesApiPermanentError)
    assert not issubclass(SmartTimesApiPayloadError, SmartTimesApiPermanentError)
    assert not issubclass(SmartTimesApiPermanentError, SmartTimesApiTimeoutError)
    assert not issubclass(SmartTimesApiPermanentError, SmartTimesApiPayloadError)


def test_user_agent_mit_version_und_doku_link():
    """Version und Doku-Link ergeben ``Produkt/Version (+URL)``."""
    ua = _build_user_agent("2.1.0", "https://github.com/da-sa-li/HA-smartenergy-Tarif")
    # Laut Spezifikation (Schema "Produkt/Version (+URL)"):
    assert ua == "HomeAssistant-Strompreishelfer/2.1.0 (+https://github.com/da-sa-li/HA-smartenergy-Tarif)"


def test_user_agent_nur_mit_version():
    """Ohne Doku-Link bleibt es bei ``Produkt/Version`` (kein Klammer-Suffix)."""
    ua = _build_user_agent("2.1.0", None)
    assert ua == "HomeAssistant-Strompreishelfer/2.1.0"


def test_user_agent_nur_mit_doku_link():
    """Ohne Version steht der Doku-Link direkt hinterm reinen Produktnamen."""
    ua = _build_user_agent(None, "https://github.com/da-sa-li/HA-smartenergy-Tarif")
    assert ua == "HomeAssistant-Strompreishelfer (+https://github.com/da-sa-li/HA-smartenergy-Tarif)"


def test_user_agent_ohne_version_und_doku_link():
    """Ohne Version/Link fällt der User-Agent auf das reine Produkt zurück."""
    # Laut Spezifikation: ohne Metadaten bleibt nur der Produktname.
    assert _build_user_agent(None, None) == "HomeAssistant-Strompreishelfer"


class _FakeResponse:
    """Minimale aiohttp-Response-Attrappe für ``async_get_prices``-Tests."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def text(self) -> str:
        """Liefert den JSON-Body als Text, wie ``ClientResponse.text()``."""
        return json.dumps(self._payload)

    def raise_for_status(self) -> None:
        """No-Op: die Fake-Antwort ist immer erfolgreich."""


class _InvalidJsonResponse:
    """Antwort-Attrappe mit einem Body, der sich nicht als JSON lesen lässt."""

    async def text(self) -> str:
        """Liefert absichtlich keinen gültigen JSON-Text."""
        return "<html>kein JSON</html>"

    def raise_for_status(self) -> None:
        """No-Op: der HTTP-Status allein ist hier erfolgreich."""


async def test_ungueltiges_json_loest_payload_fehler_aus():
    """Ein nicht auswertbarer Body löst einen Payload-Fehler aus."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=_InvalidJsonResponse())
    client = SmartTimesApiClient(session)
    with pytest.raises(SmartTimesApiPayloadError):
        await client.async_get_prices()


async def test_zeitueberschreitung_loest_timeout_fehler_aus():
    """Eine Zeitüberschreitung beim Abruf löst den eigenen Timeout-Fehler aus."""
    session = AsyncMock()
    session.get = AsyncMock(side_effect=TimeoutError())
    client = SmartTimesApiClient(session)
    with pytest.raises(SmartTimesApiTimeoutError):
        await client.async_get_prices()


async def test_client_sendet_den_gebauten_user_agent(smarttimes_payload):
    """Der gebaute User-Agent landet im tatsächlichen GET-Request-Header."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=_FakeResponse(smarttimes_payload))
    client = SmartTimesApiClient(
        session,
        integration_version="2.1.0",
        documentation_url="https://github.com/da-sa-li/HA-smartenergy-Tarif",
    )

    await client.async_get_prices()

    _, kwargs = session.get.call_args
    assert kwargs["headers"]["User-Agent"] == (
        "HomeAssistant-Strompreishelfer/2.1.0 (+https://github.com/da-sa-li/HA-smartenergy-Tarif)"
    )


# --- Fehlerklassifizierung: dauerhafte vs. vorübergehende HTTP-Fehler -------- #


class _ErrorResponse:
    """Antwort-Attrappe, deren ``raise_for_status`` einen HTTP-Fehler auslöst."""

    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        """Baut die Attrappe für einen konkreten Status samt Antwort-Headern."""
        self._error = aiohttp.ClientResponseError(
            MagicMock(),
            (),
            status=status,
            message="Fehler",
            headers=CIMultiDict(headers or {}),
        )

    async def text(self) -> str:
        """Der Body spielt bei einem Fehlerstatus keine Rolle."""
        return ""

    def raise_for_status(self) -> None:
        """Löst den vorbereiteten Fehler aus, wie ``ClientResponse`` es täte."""
        raise self._error


async def _get_prices_error(
    status: int, headers: dict[str, str] | None = None
) -> SmartTimesApiError:
    """Ruft die API mit einer fehlschlagenden Antwort auf und liefert den Fehler."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=_ErrorResponse(status, headers))
    client = SmartTimesApiClient(session)
    with pytest.raises(SmartTimesApiError) as excinfo:
        await client.async_get_prices()
    return excinfo.value


# Laut Spezifikation (RFC 9110) sind 4xx Client-Fehler, die sich durch bloßes
# Wiederholen nicht beheben lassen – Ausnahmen sind 408 und 429.
@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 451])
async def test_dauerhafte_client_fehler(status):
    """Die meisten 4xx gelten als dauerhafte Ablehnung."""
    assert isinstance(await _get_prices_error(status), SmartTimesApiPermanentError)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
async def test_voruebergehende_fehler(status):
    """408/429 sowie alle 5xx sind vorübergehend – hier wird weiter wiederholt."""
    err = await _get_prices_error(status)
    assert not isinstance(err, SmartTimesApiPermanentError)


async def test_status_bleibt_in_der_fehlermeldung():
    """Der HTTP-Status bleibt in der Fehlermeldung erhalten (Diagnose im Log)."""
    assert "503" in str(await _get_prices_error(503))


async def test_retry_after_kommt_aus_der_rate_limit_antwort():
    """Ein ``Retry-After`` bei HTTP 429 erreicht den Koordinator als Wartezeit."""
    err = await _get_prices_error(429, {"Retry-After": "90"})
    assert err.retry_after == timedelta(seconds=90)


async def test_fehler_ohne_retry_after_kopfzeile():
    """Ohne den Header bleibt ``retry_after`` leer – es gilt die eigene Wartezeit."""
    assert (await _get_prices_error(503)).retry_after is None


# --- Retry-After-Header (RFC 9110) ------------------------------------------ #


def test_retry_after_in_sekunden():
    """Die Sekunden-Schreibweise wird direkt übernommen."""
    assert _parse_retry_after("120") == timedelta(seconds=120)


def test_retry_after_ignoriert_leerzeichen():
    """Umgebende Leerzeichen stören nicht."""
    assert _parse_retry_after("  45  ") == timedelta(seconds=45)


def test_retry_after_wird_nie_negativ():
    """Ein negativer Wert ergibt keine negative Wartezeit."""
    assert _parse_retry_after("-5") == timedelta(0)


@pytest.mark.freeze_time("2026-06-05 10:00:00")
def test_retry_after_als_http_datum():
    """Ein HTTP-Datum wird in die verbleibende Wartezeit umgerechnet.

    Eingefroren ist der 05.06.2026 um 10:00:00 UTC; das Datum im Header liegt
    laut Spezifikation in GMT und damit exakt 2 Minuten später.
    """
    assert _parse_retry_after("Fri, 05 Jun 2026 10:02:00 GMT") == timedelta(minutes=2)


@pytest.mark.freeze_time("2026-06-05 10:00:00")
def test_retry_after_mit_verstrichenem_datum_ergibt_null():
    """Ein bereits verstrichenes Datum ergibt die Wartezeit null."""
    assert _parse_retry_after("Fri, 05 Jun 2026 09:58:00 GMT") == timedelta(0)


@pytest.mark.parametrize("value", [None, "", "   ", "bald", "morgen früh"])
def test_retry_after_unbrauchbar(value):
    """Fehlt der Header oder ist er unbrauchbar, gilt die eigene Wartezeit."""
    assert _parse_retry_after(value) is None


# --- Fehlertoleranz des Parsers --------------------------------------------- #
#
# Diese Zweige greifen genau dann, wenn smartENERGY die Antwort verändert – das
# Hauptrisiko einer Integration, die eine fremde, nicht versionierte API
# konsumiert. Der Live-Test bemerkt einen Formatwechsel zwar, prüft aber nicht,
# ob der Parser ihn *sauber* abfängt statt mit einem Stacktrace mitten im Setup
# auszusteigen.
#
# Maßstab ist durchweg: Ein unbrauchbarer Einzelwert kostet höchstens seinen
# eigenen Eintrag; erst wenn gar nichts Verwertbares übrig bleibt, gibt es einen
# SmartTimesApiPayloadError.


async def test_netzwerkfehler_loest_einen_api_fehler_aus():
    """Ein Verbindungsabbruch wird als allgemeiner API-Fehler gemeldet.

    Der schlichte Netzwerkfehler – abgerissene Verbindung, DNS, TLS – hatte
    bisher keinen Test, obwohl er der häufigste Fehlerfall im Betrieb ist.
    Wichtig ist, dass er NICHT als dauerhafte Ablehnung gilt: Sonst ginge der
    Koordinator sofort auf das Maximal-Intervall und eine kurze Störung kostete
    zwei Stunden Aktualität.
    """
    session = AsyncMock()
    session.get = AsyncMock(
        side_effect=aiohttp.ClientConnectionError("Verbindung abgebrochen")
    )
    client = SmartTimesApiClient(session)

    with pytest.raises(SmartTimesApiError) as excinfo:
        await client.async_get_prices()

    assert not isinstance(excinfo.value, SmartTimesApiPermanentError)
    # Der Grund bleibt in der Meldung erhalten (Diagnose im Log).
    assert "Verbindung abgebrochen" in str(excinfo.value)
    # Ohne Antwort gibt es auch keine Wartezeit-Vorgabe des Servers.
    assert excinfo.value.retry_after is None


@pytest.mark.freeze_time("2026-06-05 10:00:00")
def test_retry_after_datum_ohne_zone_gilt_als_gmt():
    """Ein HTTP-Datum ohne verwertbare Zone gilt laut RFC 9110 als GMT.

    ``-0000`` heißt „Zone unbekannt“; ``parsedate_to_datetime`` liefert dann ein
    zeitzonenloses datetime. Ohne die Annahme GMT vergliche der Code ein naives
    mit einem zeitzonenbehafteten datetime und liefe in einen TypeError – mitten
    in der Fehlerbehandlung eines ohnehin schon fehlgeschlagenen Abrufs.
    """
    # Eingefroren auf den 05.06.2026 10:00:00 UTC, das Datum liegt 2 Minuten später.
    assert _parse_retry_after("Fri, 05 Jun 2026 10:02:00 -0000") == timedelta(
        minutes=2
    )


def test_unlesbares_intervall_faellt_auf_die_viertelstunde_zurueck():
    """Ein unlesbares ``interval`` fällt auf das Viertelstundenraster zurück.

    Die Intervalllänge bestimmt das Ende jedes Preis-Eintrags. Ein Ausfall hier
    dürfte nicht den ganzen Abruf scheitern lassen – der dokumentierte Standard
    beider Tarife ist 15 Minuten.
    """
    result = SmartTimesApiClient._parse(
        {
            "energyPrice": {
                "interval": "viertelstuendlich",
                "values": [
                    {"dateTimeFrom": "2026-06-05T00:00:00+02:00", "value": 13.02}
                ],
            }
        }
    )

    assert result.interval_minutes == 15
    assert result.prices[0].end == _iso("2026-06-05T00:15:00+02:00")


@pytest.mark.parametrize(
    ("eintrag", "grund"),
    [
        ("kein Objekt", "Zeichenkette statt Objekt in der Werteliste"),
        ({"dateTimeFrom": "kein Datum", "value": 13.02}, "unlesbares Datum"),
        ({"dateTimeFrom": "2026-06-05T01:00:00+02:00", "value": "teuer"}, "Wert keine Zahl"),
        ({"dateTimeFrom": "2026-06-05T01:00:00+02:00", "value": []}, "Wert falscher Typ"),
    ],
    ids=["nicht-objekt", "kaputtes-datum", "wert-keine-zahl", "wert-falscher-typ"],
)
def test_parser_ueberspringt_einen_kaputten_eintrag(eintrag, grund):
    """Ein unbrauchbarer Eintrag kostet nur sich selbst, nicht den ganzen Abruf.

    Der gültige Eintrag daneben bleibt erhalten – ein einzelner Ausreißer in der
    Antwort darf die Preise des restlichen Tages nicht mitreißen.
    """
    result = SmartTimesApiClient._parse(
        {
            "energyPrice": {
                "interval": 15,
                "values": [
                    eintrag,
                    {"dateTimeFrom": "2026-06-05T00:00:00+02:00", "value": 13.02},
                ],
            }
        }
    )

    assert len(result.prices) == 1, grund
    assert result.prices[0].start == _iso("2026-06-05T00:00:00+02:00")


def test_grundgebuehr_ohne_werteliste_behaelt_die_einheit():
    """Fehlt die Werteliste der Grundgebühr, bleibt wenigstens die Einheit erhalten.

    Die Einheit steuert die Warnung in ``sensor.async_setup_entry`` (meldet die
    API plötzlich EUR/year statt EUR/month, zeigte der Sensor stillschweigend
    eine falsche an). Sie darf deshalb nicht mit der Werteliste verloren gehen.
    """
    result = SmartTimesApiClient._parse(
        {
            "energyPrice": {
                "values": [
                    {"dateTimeFrom": "2026-06-05T00:00:00+02:00", "value": 13.02}
                ]
            },
            "basicFee": {"unit": "EUR/month"},
        }
    )

    assert result.basic_fees == []
    assert result.basic_fee_unit == "EUR/month"


def test_grundgebuehr_ueberspringt_kaputte_eintraege():
    """Ein kaputter Grundgebühr-Eintrag wird übersprungen, der gültige bleibt."""
    result = SmartTimesApiClient._parse(
        {
            "energyPrice": {
                "values": [
                    {"dateTimeFrom": "2026-06-05T00:00:00+02:00", "value": 13.02}
                ]
            },
            "basicFee": {
                "unit": "EUR/month",
                "values": [
                    {"dateTimeFrom": "kein Datum", "value": 2.988},
                    {"dateTimeFrom": "2026-06-05T00:00:00+02:00", "value": 2.988},
                ],
            },
        }
    )

    assert [f.gross_value for f in result.basic_fees] == [2.988]


def test_grundgebuehr_falscher_form_wird_ignoriert():
    """Ist ``basicFee`` gar kein Objekt, gibt es schlicht keine Grundgebühr.

    Der Sensor entfällt dann (siehe ``sensor._is_available``), statt dauerhaft
    auf „unbekannt“ zu stehen.
    """
    result = SmartTimesApiClient._parse(
        {
            "energyPrice": {
                "values": [
                    {"dateTimeFrom": "2026-06-05T00:00:00+02:00", "value": 13.02}
                ]
            },
            "basicFee": "2,988 EUR",
        }
    )

    assert result.basic_fees == []
    assert result.basic_fee_unit is None
