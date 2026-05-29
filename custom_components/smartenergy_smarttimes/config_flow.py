"""Config-Flow für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

import logging
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
from homeassistant.helpers import selector

from .api import SmartTimesApiClient, SmartTimesApiError
from .const import (
    CONF_GRID_ZONE,
    CONF_INCLUDE_VAT,
    DEFAULT_GRID_ZONE,
    DEFAULT_INCLUDE_VAT,
    DOMAIN,
    GRID_ZONE_NONE,
)
from .grid_fees import GRID_ZONES

_LOGGER = logging.getLogger(__name__)

TITLE = "smartENERGY smartTIMES"


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
