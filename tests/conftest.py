"""Gemeinsame Fixtures für die Test-Suite.

Die Sollwerte in den Tests sind **von Hand aus der Spezifikation** (CLAUDE.md,
README) abgeleitet und nicht aus dem zu testenden Code erzeugt – nur so prüfen
die Tests die Mathematik unabhängig und werden nicht zur Tautologie.

Hier wird außerdem die Option ``--live`` bereitgestellt, die die Tests mit dem
Marker ``live`` (echte API-Abrufe, siehe ``test_api_live.py``) freischaltet.
"""

from __future__ import annotations

import json
import zoneinfo
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.coordinator import SmartTimesData
from custom_components.smartenergy.grid_fees import get_zone

FIXTURES = Path(__file__).parent / "fixtures"

# Europe/Vienna entspricht im Sommer genau dem +02:00-Offset der API-Daten.
VIENNA = zoneinfo.ZoneInfo("Europe/Vienna")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Ergänzt die Kommandozeilen-Option ``--live``.

    Dieser Hook ist nur in einer *initialen* conftest erlaubt; durch
    ``testpaths = tests`` in ``pytest.ini`` ist diese Datei genau das.
    """
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help=(
            "Führt zusätzlich die Tests aus, die die echte smartENERGY-API "
            "abrufen (Marker 'live'). Ohne die Option werden sie übersprungen."
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Überspringt ``live``-markierte Tests, solange ``--live`` fehlt.

    Bewusst überspringen statt abwählen: So bleiben die Live-Tests in der
    Zusammenfassung eines normalen Laufs sichtbar, statt stillschweigend zu
    verschwinden.
    """
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(
        reason="Live-Test gegen die echte smartENERGY-API – nur mit --live."
    )
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def _vienna_default_tz():
    """Setzt für jeden Test Europe/Vienna als Standard-Zeitzone.

    Die smartENERGY-API liefert lokale Zeitstempel; ``as_local`` rechnet gegen
    ``dt_util.DEFAULT_TIME_ZONE``. Ohne diese Festlegung würden SNAP-Fenster und
    Tagesgrenzen je nach Host-Zeitzone verrutschen.
    """
    original = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(VIENNA)
    yield
    dt_util.set_default_time_zone(original)


@pytest.fixture
async def hass(hass):  # Absicht: überschreibt die Fixture des Plugins
    """HA-Instanz auf ``Europe/Vienna`` statt auf der Vorgabe des Harness.

    ``pytest-homeassistant-custom-component`` setzt beim Hochfahren fest
    ``US/Pacific`` (``common.py``) und überschreibt damit ``_vienna_default_tz``
    oben, das nur für Tests **ohne** HA-Instanz greift.

    Für eine Integration, die es nur in Österreich gibt, ist das die falsche
    Grundlage: SNAP-Fenster (10–16 Uhr), Tagesgrenzen und „morgen“ verrutschen
    um neun Stunden. Sollwerte, die von Hand aus der Spezifikation abgeleitet
    sind, treffen dann bestenfalls zufällig zu – aus einem anderen Grund als
    dem im Kommentar dokumentierten.

    Bewusst hier zentral und nicht je Test: Vorher stand derselbe Aufruf
    fünfmal von Hand in einzelnen Testkörpern, und wer ihn vergaß, bekam still
    US/Pacific.
    """
    await hass.config.async_set_time_zone("Europe/Vienna")
    return hass


def _load(name: str) -> dict:
    """Lädt eine JSON-Fixture aus ``tests/fixtures``."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def smarttimes_payload() -> dict:
    """Echte smartTIMES-API-Antwort (verschachteltes ``energyPrice``-Format)."""
    return _load("smarttimes.json")


@pytest.fixture
def smartcontrol_payload() -> dict:
    """Echte smartCONTROL-API-Antwort (flaches ``data``-Format mit Offset)."""
    return _load("smartcontrol.json")


@pytest.fixture
def make_data():
    """Factory: baut ``SmartTimesData`` aus einer API-Antwort (wie der Koordinator)."""

    def _make(
        payload: dict,
        *,
        include_vat: bool = True,
        grid_zone: str | None = None,
        handling_fee_net: float = 0.0,
        tariff_name: str | None = None,
    ) -> SmartTimesData:
        """Parst ``payload`` und kapselt ihn als ``SmartTimesData``."""
        result = SmartTimesApiClient._parse(payload)
        return SmartTimesData(
            tariff=tariff_name or result.tariff,
            unit=result.unit,
            interval_minutes=result.interval_minutes,
            include_vat=include_vat,
            prices=result.prices,
            basic_fees=result.basic_fees,
            basic_fee_unit=result.basic_fee_unit,
            grid_zone=get_zone(grid_zone),
            handling_fee_net=handling_fee_net,
        )

    return _make


@pytest.fixture
def ohne_jitter():
    """Setzt die Last-Glättung auf 0, damit Sollzeiten exakt prüfbar sind.

    Die Jitter-Phase leitet sich aus der Subentry-ID ab, die je Testlauf neu
    vergeben wird – ohne diesen Eingriff wäre nur ein Intervall prüfbar.
    Gepatcht wird die Bindung in ``entity``, nicht die in ``jitter``: Sonst
    verstellte der Test zugleich den Abruf-Jitter des Koordinators.

    Liegt hier und nicht in einer einzelnen Testdatei, weil sowohl die
    Zeitstempel-Tests (``test_sensor.py``) als auch die Schaltflanken-Tests
    (``test_schaltverhalten.py``) darauf aufsetzen.
    """
    with patch(
        "custom_components.smartenergy.entity.cheap_phase", return_value=0.0
    ):
        yield
