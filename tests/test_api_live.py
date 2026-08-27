"""Vertragstests gegen die **echte** smartENERGY-API (smartTIMES & smartCONTROL).

Anders als die übrigen Tests arbeiten diese hier nicht mit den eingefrorenen
Antworten aus ``tests/fixtures/``, sondern rufen die öffentlichen Endpunkte
tatsächlich ab. Sie beantworten damit eine Frage, die eine Fixture nie
beantworten kann: *Liefert die API heute noch das, worauf die Integration baut?*

Geprüft werden ausschließlich **Invarianten** – niemals konkrete Preise, die
sich täglich ändern. Zusätzlich wird die Schlüsselstruktur der Live-Antwort mit
der eingecheckten Fixture verglichen, damit auffällt, wenn Felder hinzukommen,
verschwinden oder umbenannt werden (und die Fixtures nicht still veralten).

Die Sollwerte stammen aus der API-Dokumentation von smartENERGY bzw. aus
CLAUDE.md und sind unten jeweils im Kommentar belegt – nicht aus dem zu
testenden Code erzeugt.

Ausführen (Netzzugang nötig)::

    pytest -m live --live

Ohne ``--live`` werden diese Tests übersprungen (siehe ``conftest.py``), damit
die normale CI offline und unabhängig vom fremden Server bleibt.

Ist ``LIVE_ANTWORT_DIR`` gesetzt, legen sie die abgerufenen Antworten dort als
Dateien ab. Die nächtliche CI nutzt das, um sie bei einem Fehlschlag als
Artefakt an den Lauf zu hängen: Ohne sie stünde die wahrscheinlichste Diagnose
– smartENERGY hat das Antwortformat geändert – ohne Belegmaterial da.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import aiohttp
import pytest
import pytest_socket
from homeassistant.util import dt as dt_util

from custom_components.smartenergy.api import SmartTimesApiClient, SmartTimesResult
from custom_components.smartenergy.const import (
    API_OPERATOR_DOC_URL,
    API_TIMEOUT,
    TARIFF_API_URLS,
    TARIFF_SMARTCONTROL,
    TARIFF_SMARTTIMES,
)

# Alle Tests dieses Moduls rufen die echte API auf.
pytestmark = pytest.mark.live

MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "smartenergy"
    / "manifest.json"
)

# Unversehrte Netzwerkfunktionen, gesichert beim Import dieses Moduls – also
# während der Sammelphase und damit *bevor* das Home-Assistant-Test-Harness sie
# vor dem ersten Test durch seine Sperren ersetzt (siehe NETZWERK_FREIGEBEN).
ECHTE_NETZFUNKTIONEN: Final = {
    "socket": socket.socket,
    "connect": socket.socket.connect,
    "getaddrinfo": socket.getaddrinfo,
    "gethostbyname": socket.gethostbyname,
    "gethostbyname_ex": socket.gethostbyname_ex,
}

# Umgebungsvariable, die das Zielverzeichnis für die abgerufenen Antworten nennt.
# Gesetzt wird sie in der CI (siehe .github/workflows/live-api.yml); fehlt sie,
# bleibt der Lauf ohne Nebenwirkung auf der Platte.
ANTWORT_ABLAGE_ENV: Final = "LIVE_ANTWORT_DIR"

# --- Sollwerte laut Spezifikation ------------------------------------------- #

# Beide Tarife liefern laut API-Doku ein Viertelstundenraster. Auf diesem Raster
# ruht die gesamte Preis-Mathematik im Koordinator (Tageskennzahlen, Auswahl der
# günstigen Stunden); eine Änderung wäre ein Umbau, kein Detail.
ERWARTETES_INTERVALL: Final = 15

# Mindestens ein voller Tag = 96 Viertelstunden. Real liefern beide Endpunkte
# zwei Tage (192); die Untergrenze lässt Luft für den Zeitraum, bevor die
# Folgetagspreise bereitstehen (siehe NEXT_DAY_PRICES_HOUR).
MIN_INTERVALLE: Final = 96

# smartTIMES antwortet mit "cent/kWh", smartCONTROL mit "ct/kWh" – beides meint
# dieselbe Einheit, in der sensor.py rechnet.
ZULAESSIGE_EINHEITEN: Final = frozenset({"ct/kWh", "cent/kWh"})

# Plausibilitätsfenster für Bruttopreise in ct/kWh. Die Untergrenze ist bewusst
# negativ: negative EPEX-Spot-Preise kommen bei viel Wind/Sonne real vor. Die
# Obergrenze liegt weit über den Spitzen der Energiekrise 2022.
MIN_PREIS: Final = -100.0
MAX_PREIS: Final = 200.0

# Viertelstundenraster in lokaler Zeit.
ERLAUBTE_MINUTEN: Final = frozenset({0, 15, 30, 45})


@dataclass(frozen=True, slots=True)
class TarifErwartung:
    """Tarifspezifische Sollwerte für den Vertragstest."""

    tarif: str
    api_url: str
    # Wert des Feldes ``tariff`` im Ergebnis: smartTIMES führt kein solches Feld,
    # dort greift der dokumentierte Fallback des Parsers; smartCONTROL nennt den
    # Börsen-Tarif beim Namen.
    tariff_feld: str
    # Einheit des Grundgebühr-Blocks bzw. None, wenn der Tarif keinen liefert.
    basic_fee_unit: str | None
    fixture_name: str


ERWARTUNGEN: Final[tuple[TarifErwartung, ...]] = (
    TarifErwartung(
        tarif=TARIFF_SMARTTIMES,
        api_url=TARIFF_API_URLS[TARIFF_SMARTTIMES],
        tariff_feld="smartTIMES",
        basic_fee_unit="EUR/month",
        fixture_name="smarttimes_payload",
    ),
    TarifErwartung(
        tarif=TARIFF_SMARTCONTROL,
        api_url=TARIFF_API_URLS[TARIFF_SMARTCONTROL],
        tariff_feld="EPEXSPOTAT",
        basic_fee_unit=None,
        fixture_name="smartcontrol_payload",
    ),
)


# --- Hilfsmittel ------------------------------------------------------------- #


def integration_version() -> str:
    """Liest die Version aus dem Manifest (ohne den Umweg über Home Assistant)."""
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]


@pytest.fixture
def netzwerk_freigeben():
    """Hebt die Netzwerksperre des Test-Harness für die Dauer eines Tests auf.

    ``pytest-homeassistant-custom-component`` kappt vor jedem Test bewusst
    Sockets *und* die DNS-Auflösung, damit Tests nicht unbemerkt ins Netz gehen
    (``plugins.pytest_runtest_setup``). Für die Live-Tests ist genau das im Weg,
    also wird die Sperre hier gezielt zurückgenommen – nur hier, nur für diesen
    einen Test, und danach wieder hergestellt.
    """
    gesperrt = {
        "socket": socket.socket,
        "connect": socket.socket.connect,
        "getaddrinfo": socket.getaddrinfo,
        "gethostbyname": socket.gethostbyname,
        "gethostbyname_ex": socket.gethostbyname_ex,
    }
    pytest_socket.enable_socket()
    # ``enable_socket`` stellt nur die Socket-Klasse wieder her; die
    # Host-Beschränkung (auf 127.0.0.1) hängt an ``connect``, die DNS-Sperre an
    # den Namensauflösungs-Funktionen. Beides hier zurücknehmen.
    socket.socket.connect = ECHTE_NETZFUNKTIONEN["connect"]
    socket.getaddrinfo = ECHTE_NETZFUNKTIONEN["getaddrinfo"]
    socket.gethostbyname = ECHTE_NETZFUNKTIONEN["gethostbyname"]
    socket.gethostbyname_ex = ECHTE_NETZFUNKTIONEN["gethostbyname_ex"]
    try:
        yield
    finally:
        # Reihenfolge zählt: ``connect`` hängt an der Klasse, die oben verändert
        # wurde – also erst dort zurücksetzen, dann die Klasse selbst tauschen.
        # ``finally``, damit ein fehlgeschlagener Test die Sperre nicht offen lässt.
        socket.socket.connect = gesperrt["connect"]
        socket.socket = gesperrt["socket"]
        socket.getaddrinfo = gesperrt["getaddrinfo"]
        socket.gethostbyname = gesperrt["gethostbyname"]
        socket.gethostbyname_ex = gesperrt["gethostbyname_ex"]


@pytest.fixture
async def live_session(netzwerk_freigeben):
    """Echte ``aiohttp``-Session für die Abrufe.

    Funktions-Scope, weil das Home-Assistant-Test-Harness je Test einen eigenen
    Event-Loop bereitstellt.
    """
    async with aiohttp.ClientSession() as session:
        yield session


def erzeuge_client(
    session: aiohttp.ClientSession, api_url: str
) -> SmartTimesApiClient:
    """Baut den Client genau so, wie ``__init__.py`` es im Betrieb tut.

    Wichtig ist der echte User-Agent samt Version und Doku-Link: Nur so prüft der
    Test mit, dass smartENERGY unsere Anfragen nicht abweist (siehe
    ``_build_user_agent`` in ``api.py``).
    """
    return SmartTimesApiClient(
        session,
        api_url,
        integration_version=integration_version(),
        documentation_url=API_OPERATOR_DOC_URL,
    )


def lege_antwort_ab(tarif: str, text: str) -> None:
    """Legt die abgerufene Antwort für die Fehlerdiagnose auf der Platte ab.

    Schlägt der nächtliche Lauf fehl, ist die Antwort sonst mit dem Runner
    verloren – und genau sie belegt, ob smartENERGY das Format geändert hat. Die
    CI lädt das Verzeichnis als Artefakt hoch und verlinkt es im Fehler-Issue.

    Dateiname und Formatierung entsprechen der Fixture (``smarttimes.json``,
    zweifach eingerückt): So zeigt ein ``diff`` gegen ``tests/fixtures/`` nur
    echte Unterschiede statt der Minifizierung der API. Ist die Antwort kein
    JSON – etwa eine HTML-Fehlerseite –, wird sie roh als ``.txt`` abgelegt; sie
    ist dann selbst die Auskunft darüber, was schiefging.

    Ohne die Umgebungsvariable passiert nichts, damit ein lokaler Lauf nichts
    hinterlässt. Gelesen wird sie bewusst hier und nicht beim Import, sonst wäre
    die Funktion nicht mit ``monkeypatch.setenv`` prüfbar.
    """
    verzeichnis = os.environ.get(ANTWORT_ABLAGE_ENV)
    if not verzeichnis:
        return
    ziel = Path(verzeichnis)
    ziel.mkdir(parents=True, exist_ok=True)
    try:
        inhalt = json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
    except ValueError:
        (ziel / f"{tarif}.txt").write_text(text, encoding="utf-8")
        return
    (ziel / f"{tarif}.json").write_text(inhalt, encoding="utf-8")


async def hole_rohantwort(
    session: aiohttp.ClientSession, erwartung: TarifErwartung
) -> dict:
    """Ruft die Antwort unverarbeitet ab und legt sie für die Diagnose ab.

    Die Header des produktiven Clients werden bewusst wiederverwendet, damit die
    Anfrage exakt der echten entspricht. Abgelegt wird **vor**
    ``raise_for_status``, damit auch der Körper einer Fehlerantwort erhalten
    bleibt – bei einem 4xx/5xx ist gerade er die Diagnose. Das Zeitlimit umfasst
    nur den Netzverkehr, nicht das Schreiben der Datei.
    """
    client = erzeuge_client(session, erwartung.api_url)
    async with asyncio.timeout(API_TIMEOUT):
        response = await session.get(
            erwartung.api_url, headers=client._headers  # noqa: SLF001
        )
        text = await response.text()
    lege_antwort_ab(erwartung.tarif, text)
    response.raise_for_status()
    return json.loads(text)


def schluessel_struktur(wert: object) -> object:
    """Reduziert eine JSON-Struktur auf ihre reine Schlüssel-Signatur.

    Objekte werden auf ihre Schlüssel samt (rekursiver) Struktur abgebildet.
    Bei Listen werden **alle** Elemente ausgewertet und ihre Signaturen als
    sortierte Menge zurückgegeben: Eine Feldänderung erst im hundertsten
    Preiseintrag soll ebenso auffallen wie eine im ersten. Bei der homogenen
    Normalantwort bleibt genau eine Signatur übrig. Konkrete Werte fallen weg,
    verglichen wird also allein das Format.
    """
    if isinstance(wert, dict):
        return {name: schluessel_struktur(inhalt) for name, inhalt in wert.items()}
    if isinstance(wert, list):
        # Über JSON-Text vereinheitlicht, weil verschachtelte Signaturen selbst
        # Objekte sind und sich damit nicht direkt in eine Menge legen lassen.
        return sorted(
            {
                json.dumps(schluessel_struktur(element), sort_keys=True)
                for element in wert
            }
        )
    return None


def pruefe_preis_vertrag(result: SmartTimesResult) -> None:
    """Prüft die tarifunabhängigen Zusagen der API an die Integration."""
    assert result.interval_minutes == ERWARTETES_INTERVALL, (
        f"Die API liefert ein {result.interval_minutes}-Minuten-Raster statt "
        f"{ERWARTETES_INTERVALL} – die Preis-Mathematik im Koordinator geht vom "
        "Viertelstundenraster aus."
    )
    assert result.unit in ZULAESSIGE_EINHEITEN, (
        f"Unbekannte Einheit {result.unit!r}; die Sensoren rechnen in ct/kWh."
    )
    assert len(result.prices) >= MIN_INTERVALLE, (
        f"Nur {len(result.prices)} Intervalle erhalten, erwartet mindestens "
        f"{MIN_INTERVALLE} (ein voller Tag)."
    )

    zeitzone = dt_util.DEFAULT_TIME_ZONE
    for preis in result.prices:
        assert preis.start.tzinfo is not None and preis.end.tzinfo is not None, (
            f"Zeitstempel ohne Zeitzone: {preis.start} – der Parser müsste dann "
            "auf die HA-Zeitzone zurückfallen."
        )
        lokal = preis.start.astimezone(zeitzone)
        assert preis.start.utcoffset() == lokal.utcoffset(), (
            f"Offset {preis.start.utcoffset()} passt nicht zur lokalen Zeitzone "
            f"({lokal.utcoffset()}) bei {preis.start}."
        )
        assert (
            lokal.minute in ERLAUBTE_MINUTEN
            and lokal.second == 0
            and lokal.microsecond == 0
        ), f"Zeitstempel {lokal} liegt nicht auf einer Viertelstundengrenze."
        assert MIN_PREIS <= preis.gross_ct_per_kwh <= MAX_PREIS, (
            f"Unplausibler Preis {preis.gross_ct_per_kwh} ct/kWh um {lokal} – "
            "vermutlich eine andere Einheit oder ein anderer Maßstab."
        )

    # Lückenlos und aufsteigend: Ende eines Intervalls = Beginn des nächsten.
    for vorher, nachher in zip(result.prices, result.prices[1:], strict=False):
        assert vorher.end == nachher.start, (
            f"Lücke oder Überlappung im Preisraster: {vorher.end} -> "
            f"{nachher.start}."
        )

    # Der aktuelle Zeitpunkt muss abgedeckt sein – genau darauf greift
    # SmartTimesData.current_price zu.
    jetzt = dt_util.now()
    assert any(preis.start <= jetzt < preis.end for preis in result.prices), (
        f"Kein Intervall deckt den aktuellen Zeitpunkt {jetzt} ab (Daten von "
        f"{result.prices[0].start} bis {result.prices[-1].end})."
    )


# --- Tests ------------------------------------------------------------------- #


@pytest.mark.parametrize("erwartung", ERWARTUNGEN, ids=lambda e: e.tarif)
async def test_live_api_haelt_den_vertrag(
    erwartung: TarifErwartung, live_session: aiohttp.ClientSession
) -> None:
    """Der echte Abruf liefert ein verwertbares, lückenloses Preisraster.

    Läuft über ``async_get_prices`` und damit über den kompletten produktiven
    Codepfad inklusive Timeout- und Fehlerbehandlung.
    """
    client = erzeuge_client(live_session, erwartung.api_url)

    result = await client.async_get_prices()

    pruefe_preis_vertrag(result)
    assert result.tariff == erwartung.tariff_feld
    assert result.basic_fee_unit == erwartung.basic_fee_unit
    if erwartung.basic_fee_unit is None:
        assert result.basic_fees == []
    else:
        assert result.basic_fees, "Grundgebühr-Block (basicFee) fehlt in der Antwort."
        assert all(gebuehr.gross_value > 0 for gebuehr in result.basic_fees)


@pytest.mark.parametrize("erwartung", ERWARTUNGEN, ids=lambda e: e.tarif)
async def test_live_antwort_passt_zur_fixture(
    erwartung: TarifErwartung,
    live_session: aiohttp.ClientSession,
    request: pytest.FixtureRequest,
) -> None:
    """Die Live-Antwort hat dieselbe Feldstruktur wie die eingecheckte Fixture.

    Damit schlägt der Test an, sobald smartENERGY Felder ergänzt, entfernt oder
    umbenennt – auch wenn der Parser die Antwort noch verdaut. Ein neues,
    optionales Feld macht den Test bewusst ebenfalls rot: Genau dieses Signal
    will man haben. Da der Test nur nächtlich läuft, blockiert er keine PRs.
    """
    live_payload = await hole_rohantwort(live_session, erwartung)
    fixture_payload = request.getfixturevalue(erwartung.fixture_name)

    assert schluessel_struktur(live_payload) == schluessel_struktur(
        fixture_payload
    ), (
        "Das Antwortformat von "
        f"{erwartung.api_url} weicht von tests/fixtures ab. Fixture "
        f"({erwartung.fixture_name}) aktualisieren und prüfen, ob api.py._parse "
        "die Änderung abdeckt."
    )
