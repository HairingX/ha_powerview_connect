"""The library's hub for one config entry, and what Home Assistant keeps beside it."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from powerview_connect import (
    Clock,
    CoverRole,
    PowerViewError,
    PowerViewHub,
    StalledOpenRetry,
    Timing,
)

from .const import (
    CONF_MOTION_POLL_INTERVAL,
    CONF_REFRESH_MINUTES,
    DEFAULT_MOTION_POLL_INTERVAL,
    DEFAULT_REFRESH_MINUTES,
    DEFAULT_RETRY_DELAY,
    DOMAIN,
)

type PowerViewConfigEntry = ConfigEntry[PowerViewRuntime]


@dataclass(slots=True)
class RetrySettings:
    """A cover's settings for retrying an opening that stalls, as its entities hold them."""

    on: bool = False
    delay: float = DEFAULT_RETRY_DELAY
    """Seconds after each step, for the fabric to settle."""


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
    retries: dict[tuple[int, CoverRole], RetrySettings] = field(default_factory=lambda: {})
    """Each cover's settings for retrying a stalled opening, by its shade's id and its role."""

    def retry(self, shade_id: int, role: CoverRole) -> RetrySettings:
        """A cover's settings for retrying a stalled opening, the defaults until set."""
        return self.retries.setdefault((shade_id, role), RetrySettings())

    def apply_retry(self, shade_id: int, role: CoverRole) -> None:
        """Give the hub the cover's settings for retrying a stalled opening, or none while off;
        nothing for a shade the hub no longer has."""
        if shade_id not in self.hub.shades:
            return
        settings = self.retry(shade_id, role)
        retry = StalledOpenRetry(delay=settings.delay)
        self.hub.set_stalled_open_retry(shade_id, role, retry if settings.on else None)

    def via_device_id(self, shade_id: int) -> str:
        """The device id of the gateway that serves a shade."""
        gateway = self.hub.gateway_of(shade_id)
        return self.device_ids.get(gateway.serial, self.primary_device_id) if gateway else (
            self.primary_device_id)


def new_probe(hass: HomeAssistant, host: str) -> PowerViewHub:
    """A read-only hub for the gateway at `host`, to learn which home it serves."""
    return PowerViewHub(async_get_clientsession(hass), host, read_only=True)


def new_clock() -> Clock | None:
    """The clock a hub keeps time by; None for the event loop's own."""
    return None


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
