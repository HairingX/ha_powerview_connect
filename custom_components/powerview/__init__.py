"""PowerView Gen 3 (unofficial) - local push integration for Hunter Douglas / Luxaflex Gen 3 gateways."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr, service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import PowerViewClient, PowerViewError
from .const import (
    ATTR_BOTTOM,
    ATTR_TOP,
    CONF_MOTION_POLL_INTERVAL,
    CONF_REFRESH_MINUTES,
    DEFAULT_MOTION_POLL_INTERVAL,
    DEFAULT_REFRESH_MINUTES,
    DOMAIN,
    SERVICE_SET_POSITIONS,
)
from .entity import hub_device_kwargs
from .hub import PowerViewHub
from .model import parse_home

PLATFORMS: list[Platform] = [Platform.COVER, Platform.SCENE]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type PowerViewConfigEntry = ConfigEntry[PowerViewHub]

_PERCENT = vol.All(vol.Coerce(int), vol.Range(min=0, max=100))


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the set_positions entity service."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_POSITIONS,
        entity_domain=COVER_DOMAIN,
        schema={vol.Optional(ATTR_TOP): _PERCENT, vol.Optional(ATTR_BOTTOM): _PERCENT},
        func="async_set_positions",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PowerViewConfigEntry) -> bool:
    """Set up a gateway."""
    client = PowerViewClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    try:
        raw_home = await client.get_home()
    except PowerViewError as err:
        raise ConfigEntryNotReady(f"PowerView gateway {client.host} not reachable: {err}") from err

    hub = PowerViewHub(
        hass,
        entry,
        client,
        parse_home(raw_home),
        poll_interval=float(entry.options.get(CONF_MOTION_POLL_INTERVAL, DEFAULT_MOTION_POLL_INTERVAL)),
        refresh_minutes=int(entry.options.get(CONF_REFRESH_MINUTES, DEFAULT_REFRESH_MINUTES)),
    )
    entry.runtime_data = hub
    # Register the gateway first so shade devices can point at it (via_device).
    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **hub_device_kwargs(hub))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hub.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowerViewConfigEntry) -> bool:
    """Unload a gateway. Background tasks are cancelled by the config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
