"""The library's hub for one config entry, and what Home Assistant keeps beside it."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from powerview_connect import Clock, PowerViewClient, PowerViewError, PowerViewHub, SystemClock, Timing

from .const import (
    CONF_MOTION_POLL_INTERVAL,
    CONF_REFRESH_MINUTES,
    DEFAULT_MOTION_POLL_INTERVAL,
    DEFAULT_REFRESH_MINUTES,
    DOMAIN,
)

type PowerViewConfigEntry = ConfigEntry[PowerViewRuntime]


@dataclass(slots=True)
class PowerViewRuntime:
    """A config entry's hub, and the registry ids Home Assistant gave its devices."""

    hub: PowerViewHub
    unique_id: str
    """The primary gateway's serial number, which every unique id starts with."""
    device_ids: dict[str, str] = field(default_factory=lambda: {})
    """Each gateway's device id, by serial number."""
    primary_device_id: str = ""
    """The device id of the gateway the hub reaches."""
    unique_ids: set[str] = field(default_factory=lambda: set())
    """The unique id of every entity the entry has made, disabled ones included."""

    def via_device_id(self, shade_id: int) -> str:
        """The device id of the gateway that serves a shade."""
        gateway = self.hub.gateway_of(shade_id)
        return self.device_ids.get(gateway.serial, self.primary_device_id) if gateway else (
            self.primary_device_id)


def new_client(hass: HomeAssistant, host: str) -> PowerViewClient:
    """A client for the gateway at `host`, on Home Assistant's shared web session."""
    return PowerViewClient(async_get_clientsession(hass), host)


def new_clock() -> Clock:
    """The clock a hub keeps time by."""
    return SystemClock()


def timing_from(options: Mapping[str, object]) -> Timing:
    """The hub's timing, with the entry's options."""
    poll = options.get(CONF_MOTION_POLL_INTERVAL, DEFAULT_MOTION_POLL_INTERVAL)
    minutes = options.get(CONF_REFRESH_MINUTES, DEFAULT_REFRESH_MINUTES)
    return Timing(
        poll_interval=float(poll) if isinstance(poll, int | float) else DEFAULT_MOTION_POLL_INTERVAL,
        refresh_interval=60.0 * (
            minutes if isinstance(minutes, int | float) else DEFAULT_REFRESH_MINUTES),
    )


def new_hub(hass: HomeAssistant, entry: PowerViewConfigEntry, host: str) -> PowerViewHub:
    """A hub for the primary gateway at `host`, on Home Assistant's shared web session."""
    return PowerViewHub(async_get_clientsession(hass), host, timing=timing_from(entry.options),
                        clock=new_clock())


async def run_command(command: Awaitable[None]) -> None:
    """Send a command, with an error the gateway raises as one Home Assistant shows.

    Raises:
        HomeAssistantError: the gateway did not take the command.
    """
    try:
        await command
    except PowerViewError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"error": str(err)},
        ) from err
