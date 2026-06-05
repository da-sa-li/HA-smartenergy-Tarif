"""Gemeinsame Fixtures für die Test-Suite.

Die Sollwerte in den Tests sind **von Hand aus der Spezifikation** (CLAUDE.md,
README) abgeleitet und nicht aus dem zu testenden Code erzeugt – nur so prüfen
die Tests die Mathematik unabhängig und werden nicht zur Tautologie.
"""

from __future__ import annotations

import json
import zoneinfo
from pathlib import Path

import pytest
from homeassistant.util import dt as dt_util

from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.coordinator import SmartTimesData
from custom_components.smartenergy.grid_fees import get_zone

FIXTURES = Path(__file__).parent / "fixtures"

# Europe/Vienna entspricht im Sommer genau dem +02:00-Offset der API-Daten.
VIENNA = zoneinfo.ZoneInfo("Europe/Vienna")


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
