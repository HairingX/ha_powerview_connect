"""Add a gateway, find one on the network, and change where it is reached."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from powerview_connect import PowerViewError

from .const import (
    CONF_MOTION_POLL_INTERVAL,
    CONF_REFRESH_MINUTES,
    CONF_STALL_MIN_POSITION,
    CONF_STALL_PAUSE,
    DEFAULT_MOTION_POLL_INTERVAL,
    DEFAULT_REFRESH_MINUTES,
    DEFAULT_STALL_MIN_POSITION,
    DEFAULT_STALL_PAUSE,
    DOMAIN,
)
from .runtime import PowerViewConfigEntry, new_probe

_LOGGER = logging.getLogger(__name__)

SCHEMA = probatio.Schema({probatio.Required(CONF_HOST): str})


@dataclass(frozen=True)
class FoundGateway:
    """What the flow learns from a gateway."""

    host: str
    serial: str
    """The primary gateway's serial number, which tells the home apart."""
    title: str


class FlowError(Exception):
    """A gateway that cannot be added, with the reason's translation key."""

    def __init__(self, reason: str, **placeholders: str) -> None:
        """An error for `reason`."""
        super().__init__(reason)
        self.reason = reason
        self.placeholders = placeholders


class PowerViewConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a home by its primary gateway, recognised by that gateway's serial number."""

    VERSION = 1
    MINOR_VERSION = 1

    _discovered: FoundGateway

    async def _identify(self, host: str) -> FoundGateway:
        """The primary gateway at `host`.

        Raises:
            FlowError: nothing answers there as a gateway, it is an auxiliary gateway, or the
                home has no shades.
        """
        if not host:
            raise FlowError("invalid_host")
        probe = new_probe(self.hass, host)
        try:
            await probe.load()
        except PowerViewError as err:
            _LOGGER.debug("No PowerView gateway answers at %s: %s", probe.host, err)
            raise FlowError("cannot_connect") from err
        home = probe.home
        primary, here = home.primary_gateway, home.gateway_at(probe.host)
        if primary is None:
            raise FlowError("cannot_connect")
        if here is not None and not here.is_primary:
            raise FlowError("not_primary", primary=primary.ip or primary.name)
        if not home.shades:
            raise FlowError("no_shades")
        return FoundGateway(probe.host, primary.serial, f"PowerView {primary.name}")

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the primary gateway's address, and add its home."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"primary": "-"}
        if user_input is not None:
            try:
                found = await self._identify(str(user_input[CONF_HOST]).strip())
            except FlowError as err:
                errors["base"] = err.reason
                placeholders.update(err.placeholders)
            else:
                await self.async_set_unique_id(found.serial)
                # The same home at a new address: move the entry there.
                self._abort_if_unique_id_configured(updates={CONF_HOST: found.host})
                return self.async_create_entry(title=found.title, data={CONF_HOST: found.host})
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """A gateway announced itself on the network; offer to add its home.

        It is reached at the address announced, and at the port unless that is HTTP's own.

        An auxiliary gateway is not offered, as the primary one serves the whole home. A home
        already configured has its entry moved to the address announced.
        """
        host = discovery_info.host
        if discovery_info.port not in (None, 80):
            host = f"{host}:{discovery_info.port}"
        self._async_abort_entries_match({CONF_HOST: host})
        try:
            found = await self._identify(host)
        except FlowError as err:
            return self.async_abort(reason=err.reason)
        await self.async_set_unique_id(found.serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: found.host})
        self._discovered = found
        self.context["title_placeholders"] = {"name": found.title}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask before adding a discovered home."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered.title, data={CONF_HOST: self._discovered.host}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._discovered.title, "host": self._discovered.host},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address of the primary gateway; it must be the same home."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"primary": "-"}
        if user_input is not None:
            try:
                found = await self._identify(str(user_input[CONF_HOST]).strip())
            except FlowError as err:
                errors["base"] = err.reason
                placeholders.update(err.placeholders)
            else:
                await self.async_set_unique_id(found.serial)
                self._abort_if_unique_id_mismatch(reason="wrong_gateway")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: found.host}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA, user_input if user_input is not None else entry.data
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: PowerViewConfigEntry) -> PowerViewOptionsFlow:
        """The options of a configured home."""
        return PowerViewOptionsFlow()


class PowerViewOptionsFlow(OptionsFlowWithReload):
    """How often a moving shade and the whole home are read, and how curtains that stop short of
    fully open are raised; the entry reloads on a change."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = probatio.Schema({
            probatio.Required(CONF_MOTION_POLL_INTERVAL, default=DEFAULT_MOTION_POLL_INTERVAL):
                probatio.All(probatio.Coerce(float), probatio.Range(min=0.5, max=10)),
            probatio.Required(CONF_REFRESH_MINUTES, default=DEFAULT_REFRESH_MINUTES):
                probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=120)),
            probatio.Required(CONF_STALL_PAUSE, default=DEFAULT_STALL_PAUSE):
                probatio.All(probatio.Coerce(float), probatio.Range(min=0, max=120)),
            probatio.Required(CONF_STALL_MIN_POSITION, default=DEFAULT_STALL_MIN_POSITION):
                probatio.All(probatio.Coerce(int), probatio.Range(min=0, max=99)),
        })
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, self.config_entry.options),
        )
