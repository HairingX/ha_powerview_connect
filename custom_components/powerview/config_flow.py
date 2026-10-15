"""Config flow for PowerView Gen 3 (unofficial)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PowerViewClient, PowerViewError
from .const import (
    CONF_MOTION_POLL_INTERVAL,
    CONF_REFRESH_MINUTES,
    DEFAULT_MOTION_POLL_INTERVAL,
    DEFAULT_REFRESH_MINUTES,
    DOMAIN,
)
from .model import parse_home


class PowerViewConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Gen 3 gateway by IP address."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the primary gateway's address."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"primary": "?"}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            client = PowerViewClient(async_get_clientsession(self.hass), host)
            try:
                home = parse_home(await client.get_home())
            except PowerViewError:
                errors["base"] = "cannot_connect"
            else:
                matched = home.gateway_for_host(client.host)
                primary = home.primary_gateway
                if matched is not None and not matched.is_primary:
                    errors["base"] = "not_primary"
                    placeholders["primary"] = (primary.ip if primary and primary.ip else "?")
                elif not home.shades:
                    errors["base"] = "no_shades"
                else:
                    unique_id = (primary.serial if primary else None) or home.home_id or client.host
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured(updates={CONF_HOST: client.host})
                    title = f"PowerView ({primary.name})" if primary else "PowerView"
                    return self.async_create_entry(title=title, data={CONF_HOST: client.host})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PowerViewOptionsFlow:
        """Return the options flow."""
        return PowerViewOptionsFlow()


class PowerViewOptionsFlow(OptionsFlowWithReload):
    """Tuning options; the entry reloads when they change."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MOTION_POLL_INTERVAL,
                    default=options.get(CONF_MOTION_POLL_INTERVAL, DEFAULT_MOTION_POLL_INTERVAL),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=10)),
                vol.Required(
                    CONF_REFRESH_MINUTES,
                    default=options.get(CONF_REFRESH_MINUTES, DEFAULT_REFRESH_MINUTES),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
