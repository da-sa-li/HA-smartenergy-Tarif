"""Config-Flow für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SmartTimesApiClient, SmartTimesApiError
from .const import CONF_INCLUDE_VAT, DEFAULT_INCLUDE_VAT, DOMAIN

TITLE = "smartENERGY smartTIMES"


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
            except SmartTimesApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=TITLE,
                    data={},
                    options={
                        CONF_INCLUDE_VAT: user_input.get(
                            CONF_INCLUDE_VAT, DEFAULT_INCLUDE_VAT
                        )
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_INCLUDE_VAT, default=DEFAULT_INCLUDE_VAT
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SmartTimesOptionsFlow:
        """Liefert den Options-Flow."""
        return SmartTimesOptionsFlow()


class SmartTimesOptionsFlow(OptionsFlow):
    """Erlaubt das nachträgliche Ändern der Optionen."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verwaltet die Optionen."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_INCLUDE_VAT, DEFAULT_INCLUDE_VAT
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_INCLUDE_VAT, default=current): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
