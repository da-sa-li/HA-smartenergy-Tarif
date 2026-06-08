"""Tests der Diagnose-Plattform (``async_get_config_entry_diagnostics``).

Der Zeitpunkt wird eingefroren, damit Strom-/SNAP-Stichproben deterministisch
sind. 2026-06-05 10:30 UTC entspricht 12:30 Europe/Vienna (Sommerzeit,
+02:00) – mitten im SNAP-Fenster (April-September, 10-16 Uhr) und im
Abdeckungszeitraum der smartTIMES-Fixture.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.diagnostics import async_get_config_entry_diagnostics

DOMAIN = "smartenergy"


def _local(value: str) -> datetime:
    """Kurzschreibweise für ein ISO-8601-datetime mit Wiener Sommerzeit-Offset."""
    return datetime.fromisoformat(f"2026-06-05T{value}+02:00")


@pytest.mark.freeze_time("2026-06-05 10:30:00")
async def test_diagnostics_snapshot(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Der Schnappschuss spiegelt Konfiguration, Cache und Stichproben wider."""
    await hass.config.async_set_time_zone("Europe/Vienna")
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["config"] == {
        "data": {},
        "options": {"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
    }
    assert diagnostics["subentries"] == []

    coordinator_diag = diagnostics["coordinator"]
    assert coordinator_diag["tariff"] == "smartTIMES"
    assert coordinator_diag["interval_minutes"] == 15
    assert coordinator_diag["include_vat"] is True
    # Fixture deckt den 05. und 06.06.2026 ab: 2 Tage x 96 Viertelstunden.
    assert coordinator_diag["price_count"] == 192
    assert coordinator_diag["grid_zone"] == {"key": "wien", "name": "Wien"}
    # 12:30 Uhr im Juni -> SNAP-Fenster (April-September, 10-16 Uhr) aktiv.
    assert coordinator_diag["snap_active"] is True
    assert coordinator_diag["handling_fee_net"] == 0.0
    assert coordinator_diag["last_fetch"] == dt_util.now()

    # Laufendes Intervall 12:30-12:45 und das direkt folgende 12:45-13:00
    # (beide brutto 11,316 ct/kWh laut Fixture).
    assert coordinator_diag["current_interval"] == {
        "start": _local("12:30:00"),
        "end": _local("12:45:00"),
        "gross_ct_per_kwh": 11.316,
    }
    assert coordinator_diag["next_interval"] == {
        "start": _local("12:45:00"),
        "end": _local("13:00:00"),
        "gross_ct_per_kwh": 11.316,
    }

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
