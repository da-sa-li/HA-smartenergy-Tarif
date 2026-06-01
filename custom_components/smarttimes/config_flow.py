"""Config-Flow für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import SmartTimesApiClient, SmartTimesApiError
from .const import (
    CONF_CHEAP_HOURS,
    CONF_GRID_ZONE,
    CONF_INCLUDE_VAT,
    DEFAULT_CHEAP_HOURS,
    DEFAULT_GRID_ZONE,
    DEFAULT_INCLUDE_VAT,
    DOMAIN,
    GRID_ZONE_NONE,
    SUBENTRY_TYPE_CHEAP_HOUR,
)
from .grid_fees import GRID_ZONES

_LOGGER = logging.getLogger(__name__)

TITLE = "smartTIMES Strompreishelfer"


def _grid_zone_selector() -> selector.SelectSelector:
    """Dropdown zur Auswahl des Netzgebiets (für die Netzentgelte)."""
    options = [GRID_ZONE_NONE, *GRID_ZONES]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="grid_zone",
        )
    )


def _cheap_hours_selector() -> selector.NumberSelector:
    """Eingabefeld für die Anzahl günstiger Stunden pro Tag."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.25,
            max=24,
            step=0.25,
            unit_of_measurement="h",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _schema(include_vat: bool, grid_zone: str) -> vol.Schema:
    """Gemeinsames Schema für Einrichtung und Optionen."""
    return vol.Schema(
        {
            vol.Required(CONF_INCLUDE_VAT, default=include_vat): bool,
            vol.Required(
                CONF_GRID_ZONE, default=grid_zone
            ): _grid_zone_selector(),
        }
    )


def _cheap_hour_schema(
    name: str | None = None, cheap_hours: float = DEFAULT_CHEAP_HOURS
) -> vol.Schema:
    """Schema für einen „Günstige Stunde"-Untereintrag (Name + Stundenzahl).

    Der Name wird hier nur als ``str`` typisiert, damit das Schema für das
    Frontend serialisierbar bleibt (Callables/Validatoren wie ``vol.All`` mit
    Lambda lassen sich nicht serialisieren). Das Trimmen und die Leerwert-
    Prüfung passieren stattdessen im Flow-Schritt.
    """
    name_key = (
        vol.Required(CONF_NAME)
        if name is None
        else vol.Required(CONF_NAME, default=name)
    )
    return vol.Schema(
        {
            name_key: str,
            vol.Required(
                CONF_CHEAP_HOURS, default=cheap_hours
            ): _cheap_hours_selector(),
        }
    )


class SmartTimesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Behandelt die Einrichtung über die Benutzeroberfläche."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Erster (und einziger) Einrichtungsschritt."""
        # Die API liefert für alle Nutzer dieselben Daten – nur eine Instanz.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = SmartTimesApiClient(session)
            try:
                await client.async_get_prices()
            except SmartTimesApiError as err:
                # Genaue Ursache ins Log schreiben, damit sie diagnostizierbar ist.
                _LOGGER.error("Einrichtung von smartTIMES fehlgeschlagen: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=TITLE,
                    data={},
                    options={
                        CONF_INCLUDE_VAT: user_input.get(
                            CONF_INCLUDE_VAT, DEFAULT_INCLUDE_VAT
                        ),
                        CONF_GRID_ZONE: user_input.get(
                            CONF_GRID_ZONE, DEFAULT_GRID_ZONE
                        ),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(DEFAULT_INCLUDE_VAT, DEFAULT_GRID_ZONE),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SmartTimesOptionsFlow:
        """Liefert den Options-Flow."""
        return SmartTimesOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """„Günstige Stunde"-Sensoren als Untereinträge unterstützen."""
        return {SUBENTRY_TYPE_CHEAP_HOUR: CheapHourSubentryFlowHandler}


class SmartTimesOptionsFlow(OptionsFlow):
    """Erlaubt das nachträgliche Ändern der Optionen."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verwaltet die Optionen."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                options.get(CONF_INCLUDE_VAT, DEFAULT_INCLUDE_VAT),
                options.get(CONF_GRID_ZONE, DEFAULT_GRID_ZONE),
            ),
        )


class CheapHourSubentryFlowHandler(ConfigSubentryFlow):
    """Flow zum Anlegen und Bearbeiten eines „Günstige Stunde"-Sensors."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Einen neuen „Günstige Stunde"-Sensor (Untereintrag) anlegen."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            else:
                return self.async_create_entry(
                    title=name,
                    data={CONF_CHEAP_HOURS: user_input[CONF_CHEAP_HOURS]},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_cheap_hour_schema(
                # Bei einem Fehler die bereits eingegebenen Werte erhalten,
                # statt das Formular auf die Defaults zurückzusetzen.
                name=user_input.get(CONF_NAME) if user_input else None,
                cheap_hours=(
                    user_input.get(CONF_CHEAP_HOURS, DEFAULT_CHEAP_HOURS)
                    if user_input
                    else DEFAULT_CHEAP_HOURS
                ),
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Einen bestehenden „Günstige Stunde"-Sensor bearbeiten."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            else:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=name,
                    data={CONF_CHEAP_HOURS: user_input[CONF_CHEAP_HOURS]},
                )
        stored_cheap_hours = subentry.data.get(CONF_CHEAP_HOURS, DEFAULT_CHEAP_HOURS)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_cheap_hour_schema(
                # Bei einem Fehler die Eingaben erhalten, sonst die
                # gespeicherten Werte des Untereintrags vorbefüllen.
                name=(
                    user_input.get(CONF_NAME)
                    if user_input is not None
                    else subentry.title
                ),
                cheap_hours=(
                    user_input.get(CONF_CHEAP_HOURS, stored_cheap_hours)
                    if user_input is not None
                    else stored_cheap_hours
                ),
            ),
            errors=errors,
        )
