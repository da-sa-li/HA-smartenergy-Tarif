"""Tests des Config-Flows: Einrichtung, Verbindungstest, Optionen, Untereinträge."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import (
    SmartTimesApiClient,
    SmartTimesApiError,
    SmartTimesApiPayloadError,
    SmartTimesApiPermanentError,
    SmartTimesApiTimeoutError,
)
from custom_components.smartenergy.config_flow import (
    _async_validate_tariff_connection,
)

DOMAIN = "smartenergy"

# Patch-Ziel an der Quelle, damit sowohl der Flow als auch das Setup es sehen.
_PATCH_PRICES = "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices"
_PATCH_SETUP = "custom_components.smartenergy.async_setup_entry"


async def test_user_flow_creates_entry(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Erfolgreicher Flow legt den Eintrag mit den gewählten Optionen an."""
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
    """Ein Verbindungsfehler zeigt das Formular mit ``cannot_connect`` erneut."""
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
    """Existiert bereits ein Eintrag, bricht ein zweiter Flow ab."""
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    # Wegen "single_config_entry": true im Manifest bricht Home Assistant schon
    # VOR async_step_user ab – mit diesem Grund, nicht mit "already_configured".
    # Der Grund wird mitgeprüft, weil sonst ein fehlender Übersetzungstext
    # unbemerkt bliebe (die Oberfläche zeigte dann den rohen Schlüssel).
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_updates_options_and_title(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Der Options-Flow aktualisiert Optionen und passt den Titel dem Tarif an."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="smartTIMES Strompreishelfer",
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
    )
    entry.add_to_hass(hass)

    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    with patch(_PATCH_PRICES, AsyncMock(return_value=parsed)), patch(
        _PATCH_SETUP, return_value=True
    ), patch("custom_components.smartenergy.async_unload_entry", return_value=True):
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


async def test_options_flow_tariff_change_cannot_connect(
    hass: HomeAssistant, enable_custom_integrations
):
    """Ein Verbindungsfehler bei Tarifwechsel zeigt das Formular erneut, ohne zu speichern."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="smartTIMES Strompreishelfer",
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
    )
    entry.add_to_hass(hass)

    with patch(_PATCH_PRICES, AsyncMock(side_effect=SmartTimesApiError("boom"))):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"tariff": "smartcontrol", "include_vat": True, "grid_zone": "none"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    # Weder Optionen noch Titel wurden verändert.
    assert entry.options["tariff"] == "smarttimes"
    assert entry.title == "smartTIMES Strompreishelfer"


async def test_options_flow_skips_connection_check_when_tariff_unchanged(
    hass: HomeAssistant, enable_custom_integrations
):
    """Bleibt der Tarif gleich, wird die API nicht abgefragt – auch nicht bei Störung."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="smartTIMES Strompreishelfer",
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
    )
    entry.add_to_hass(hass)

    prices_mock = AsyncMock(side_effect=SmartTimesApiError("boom"))
    with patch(_PATCH_PRICES, prices_mock), patch(
        _PATCH_SETUP, return_value=True
    ), patch("custom_components.smartenergy.async_unload_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"tariff": "smarttimes", "include_vat": False, "grid_zone": "wien"},
        )
        await hass.async_block_till_done()

    prices_mock.assert_not_called()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["grid_zone"] == "wien"
    assert entry.options["include_vat"] is False


@pytest.mark.parametrize(
    ("fehler", "erwarteter_schluessel"),
    [
        (SmartTimesApiTimeoutError("boom"), "timeout"),
        (SmartTimesApiPermanentError("boom"), "api_rejected"),
        (SmartTimesApiPayloadError("boom"), "invalid_response"),
        (SmartTimesApiError("boom"), "cannot_connect"),
    ],
)
async def test_validate_tariff_connection_maps_error_types(
    hass: HomeAssistant,
    enable_custom_integrations,
    fehler: SmartTimesApiError,
    erwarteter_schluessel: str,
):
    """Jede API-Fehlerart liefert ihren eigenen Übersetzungsschlüssel."""
    with patch(_PATCH_PRICES, AsyncMock(side_effect=fehler)):
        result = await _async_validate_tariff_connection(hass, "smarttimes")
    assert result == erwarteter_schluessel


async def test_subentry_create(hass: HomeAssistant, enable_custom_integrations):
    """Der Untereintrags-Flow legt einen „Günstige Stunde"-Sensor an."""
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

    # Spezifikation: Fehlt "exact_hours" in der Eingabe – etwa von einem älteren
    # Client –, greift die Vorgabe. Sie steht seit Schema-Version 2 auf "ein":
    # Die eingestellte Stundenzahl gilt exakt. Sollergebnis: True.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Boiler", "cheap_hours": 4.0, "cheap_mode": "individual"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Boiler"
    assert result["data"] == {
        "cheap_hours": 4.0,
        "cheap_mode": "individual",
        "exact_hours": True,
    }


async def test_subentry_create_with_exact_hours(
    hass: HomeAssistant, enable_custom_integrations
):
    """Die Option „Stundenzahl exakt einhalten" wird im Untereintrag gespeichert."""
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
        {
            "name": "Waschmaschine",
            "cheap_hours": 2.0,
            "cheap_mode": "individual",
            "exact_hours": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Spezifikation: Wird die Option gesetzt, hält der Sensor die Stundenzahl
    # exakt ein. Sollergebnis: Der gespeicherte Wert ist True.
    assert result["data"]["exact_hours"] is True


async def test_subentry_name_required(
    hass: HomeAssistant, enable_custom_integrations
):
    """Ein leerer Name im Untereintrags-Flow erzeugt den Fehler ``name_required``."""
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
