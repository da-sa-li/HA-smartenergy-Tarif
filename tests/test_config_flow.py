"""Tests des Config-Flows: Einrichtung, Verbindungstest, Optionen, Untereinträge."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient, SmartTimesApiError

DOMAIN = "smartenergy"

# Patch-Ziel an der Quelle, damit sowohl der Flow als auch das Setup es sehen.
_PATCH_PRICES = "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices"
_PATCH_SETUP = "custom_components.smartenergy.async_setup_entry"


async def test_user_flow_creates_entry(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    with patch(_PATCH_PRICES, AsyncMock(return_value=parsed)), patch(
        _PATCH_SETUP, return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"tariff": "smartcontrol", "include_vat": True, "grid_zone": "wien"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "smartCONTROL Strompreishelfer"
    assert result["options"] == {
        "tariff": "smartcontrol",
        "include_vat": True,
        "grid_zone": "wien",
    }


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, enable_custom_integrations
):
    with patch(_PATCH_PRICES, AsyncMock(side_effect=SmartTimesApiError("boom"))):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_only_single_instance_allowed(
    hass: HomeAssistant, enable_custom_integrations
):
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT


async def test_options_flow_updates_options_and_title(
    hass: HomeAssistant, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="smartTIMES Strompreishelfer",
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
    )
    entry.add_to_hass(hass)

    with patch(_PATCH_SETUP, return_value=True), patch(
        "custom_components.smartenergy.async_unload_entry", return_value=True
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"tariff": "smartcontrol", "include_vat": False, "grid_zone": "wien"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["tariff"] == "smartcontrol"
    assert entry.options["grid_zone"] == "wien"
    # Titel folgt dem neuen Tarif.
    assert entry.title == "smartCONTROL Strompreishelfer"


async def test_subentry_create(hass: HomeAssistant, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cheap_hour"),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Boiler", "cheap_hours": 4.0, "cheap_mode": "individual"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Boiler"


async def test_subentry_name_required(
    hass: HomeAssistant, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cheap_hour"),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "   ", "cheap_hours": 4.0, "cheap_mode": "individual"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_required"}
