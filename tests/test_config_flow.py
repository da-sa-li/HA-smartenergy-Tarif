"""Tests des Config-Flows: Einrichtung, Verbindungstest, Optionen, Untereinträge."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
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


async def test_einrichtung_legt_den_eintrag_an(
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


async def test_einrichtung_mit_smartnight_legt_den_eintrag_an(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """smartNIGHT ist wählbar und trägt seinen eigenen Titel.

    Die Verbindungsprüfung läuft über den ableitenden Client, der die
    smartTIMES-API abruft – gepatcht wird deshalb die Basisklasse.
    """
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    with patch(_PATCH_PRICES, AsyncMock(return_value=parsed)), patch(
        _PATCH_SETUP, return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"tariff": "smartnight", "include_vat": True, "grid_zone": "none"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "smartNIGHT Strompreishelfer"
    assert result["options"] == {
        "tariff": "smartnight",
        "include_vat": True,
        "grid_zone": "none",
    }


async def test_einrichtung_meldet_einen_verbindungsfehler(
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


async def test_nur_eine_instanz_erlaubt(
    hass: HomeAssistant, enable_custom_integrations
):
    """Existiert bereits ein Eintrag, bricht ein zweiter Flow ab."""
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    # Wegen "single_config_entry": true im Manifest bricht Home Assistant schon
    # VOR async_step_user ab. Das ist der einzige Abbruchgrund dieses Flows –
    # ein eigener Aufruf von _abort_if_unique_id_configured() käme nie zum Zug
    # und wurde deshalb entfernt.
    # Der Grund wird mitgeprüft, weil sonst ein fehlender Übersetzungstext
    # unbemerkt bliebe (die Oberfläche zeigte dann den rohen Schlüssel).
    assert result["reason"] == "single_instance_allowed"


async def test_optionen_aktualisieren_werte_und_titel(
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


async def test_tarifwechsel_laedt_nur_einmal_neu(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Titel- und Optionsänderung lösen zusammen nur einen Reload aus.

    Titel und Optionen werden in einem einzigen ``async_update_entry``-Aufruf
    gesetzt; die anschließende ``async_create_entry``-Rückgabe aktualisiert
    die Optionen intern zwar noch einmal, das bleibt aber wirkungslos, da sie
    bereits auf demselben Stand stehen. Ohne das würde ein Tarifwechsel (der
    zugleich den Titel ändert) zwei Reloads statt einem auslösen.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="smartTIMES Strompreishelfer",
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
    )
    entry.add_to_hass(hass)

    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    with patch(_PATCH_PRICES, AsyncMock(return_value=parsed)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        reload_mock = AsyncMock(wraps=hass.config_entries.async_reload)
        with patch.object(hass.config_entries, "async_reload", reload_mock):
            result = await hass.config_entries.options.async_init(entry.entry_id)
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {"tariff": "smartcontrol", "include_vat": False, "grid_zone": "wien"},
            )
            await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert reload_mock.call_count == 1


async def test_tarifwechsel_meldet_einen_verbindungsfehler(
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


async def test_ohne_tarifwechsel_keine_verbindungspruefung(
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
async def test_jede_fehlerart_hat_ihren_uebersetzungsschluessel(
    hass: HomeAssistant,
    enable_custom_integrations,
    fehler: SmartTimesApiError,
    erwarteter_schluessel: str,
):
    """Jede API-Fehlerart liefert ihren eigenen Übersetzungsschlüssel."""
    with patch(_PATCH_PRICES, AsyncMock(side_effect=fehler)):
        result = await _async_validate_tariff_connection(hass, "smarttimes")
    assert result == erwarteter_schluessel


async def test_untereintrag_anlegen(hass: HomeAssistant, enable_custom_integrations):
    """Der Untereintrags-Flow legt einen „Günstige Stunde“-Sensor an."""
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


async def test_untereintrag_anlegen_mit_exact_hours(
    hass: HomeAssistant, enable_custom_integrations
):
    """Die Option „Stundenzahl exakt einhalten“ wird im Untereintrag gespeichert."""
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


async def test_untereintrag_verlangt_einen_namen(
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


# --- Untereintrag bearbeiten (reconfigure) ---------------------------------- #
#
# Bislang war ausschließlich das Anlegen eines Untereintrags getestet; der
# Bearbeiten-Schritt hatte keine einzige Zeile Abdeckung. Er ist aber der Weg,
# auf dem Nutzer Stundenzahl, Auswahllogik und „Stundenzahl exakt einhalten“
# eines bestehenden Verbrauchers ändern – mit eigener Vorbefüllungs- und
# Prüflogik, die die des Anlegen-Schritts spiegelt.

BESTAND = {"cheap_hours": 4.0, "cheap_mode": "individual", "exact_hours": True}


def _eintrag_mit_untereintrag(hass: HomeAssistant) -> tuple[MockConfigEntry, str]:
    """Legt einen Eintrag mit einem „Günstige Stunde“-Untereintrag „Boiler“ an."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
        subentries_data=[
            ConfigSubentryData(
                data=dict(BESTAND),
                subentry_type="cheap_hour",
                title="Boiler",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry, next(iter(entry.subentries))


async def _reconfigure_starten(
    hass: HomeAssistant, entry: MockConfigEntry, subentry_id: str
):
    """Startet den Bearbeiten-Flow für einen bestehenden Untereintrag."""
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cheap_hour"),
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "subentry_id": subentry_id,
        },
    )


async def test_untereintrag_bearbeiten_ist_vorbefuellt(
    hass: HomeAssistant, enable_custom_integrations
):
    """Das Formular zeigt die gespeicherten Werte und den bisherigen Namen.

    Der Name steht im *Titel* des Untereintrags, nicht in dessen ``data`` – ohne
    die ausdrückliche Vorbefüllung stünde dort ein leeres Feld, und wer nur die
    Stundenzahl ändern will, müsste den Namen neu tippen.
    """
    entry, subentry_id = _eintrag_mit_untereintrag(hass)

    result = await _reconfigure_starten(hass, entry, subentry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    # Voluptuous füllt bei leerer Eingabe die im Schema hinterlegten Vorgaben ein
    # – das ist genau die Vorbefüllung, die der Nutzer im Formular sieht.
    assert result["data_schema"]({}) == {"name": "Boiler", **BESTAND}


async def test_untereintrag_bearbeiten_speichert_aenderungen(
    hass: HomeAssistant, enable_custom_integrations
):
    """Geänderte Werte landen im Untereintrag, der Titel folgt dem neuen Namen."""
    entry, subentry_id = _eintrag_mit_untereintrag(hass)

    result = await _reconfigure_starten(hass, entry, subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Wallbox",
            "cheap_hours": 6.0,
            "cheap_mode": "consecutive",
            "exact_hours": False,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    subentry = entry.subentries[subentry_id]
    assert subentry.title == "Wallbox"
    assert subentry.data == {
        "cheap_hours": 6.0,
        "cheap_mode": "consecutive",
        "exact_hours": False,
    }
    # Derselbe Untereintrag, kein zweiter daneben: Sonst verlöre der zugehörige
    # Sensor seine Identität (unique_id und Jitter-Phase hängen an dieser ID).
    assert list(entry.subentries) == [subentry_id]


async def test_untereintrag_bearbeiten_verlangt_einen_namen(
    hass: HomeAssistant, enable_custom_integrations
):
    """Ein leerer Name wird abgewiesen und nichts gespeichert.

    Dieselbe Zusage wie beim Anlegen (``test_untereintrag_verlangt_einen_namen``) – hier ist
    sie wichtiger, weil ein Fehlschlag sonst einen bereits benannten Sensor
    entnennen würde.
    """
    entry, subentry_id = _eintrag_mit_untereintrag(hass)

    result = await _reconfigure_starten(hass, entry, subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "   ",
            "cheap_hours": 6.0,
            "cheap_mode": "consecutive",
            "exact_hours": False,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_required"}
    # Der Untereintrag ist unangetastet geblieben.
    assert entry.subentries[subentry_id].title == "Boiler"
    assert entry.subentries[subentry_id].data == BESTAND


async def test_untereintrag_bearbeiten_haelt_die_eingaben_bei_fehler(
    hass: HomeAssistant, enable_custom_integrations
):
    """Nach dem Namensfehler bleiben die übrigen Eingaben im Formular stehen.

    Sonst fiele das Formular auf die gespeicherten Werte zurück und die soeben
    getroffene Auswahl wäre weg – der Nutzer müsste alles erneut einstellen.
    """
    entry, subentry_id = _eintrag_mit_untereintrag(hass)

    result = await _reconfigure_starten(hass, entry, subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "",
            "cheap_hours": 6.0,
            "cheap_mode": "consecutive",
            "exact_hours": False,
        },
    )

    assert result["data_schema"]({}) == {
        "name": "",
        "cheap_hours": 6.0,
        "cheap_mode": "consecutive",
        "exact_hours": False,
    }
