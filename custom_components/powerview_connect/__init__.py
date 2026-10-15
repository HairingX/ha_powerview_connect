"""The PowerView Connect integration: Hunter Douglas / Luxaflex shades through a Gen 3 gateway."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import probatio
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.typing import ConfigType
from powerview_connect import PowerViewError

from .const import ATTR_BOTTOM, ATTR_TOP, DOMAIN, SERVICE_SET_POSITIONS
from .entity import gateway_device, gateway_identifier, shade_identifier
from .hub import PowerViewConfigEntry, PowerViewHub, new_client

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR, Platform.BUTTON, Platform.COVER, Platform.SCENE, Platform.SENSOR
]
# Home Assistant's own annotations of these two leave types unknown to a strict check: a bare
# `dict`, and probatio's generic `All`. They are taken by name, with the types they have.
_config_entry_only_config_schema = cast(
    Callable[[str], Callable[[ConfigType], ConfigType]],
    getattr(cv, "config_entry_only_config_schema"),
)
_register_platform_entity_service = cast(
    Callable[..., None], getattr(service, "async_register_platform_entity_service")
)

CONFIG_SCHEMA = _config_entry_only_config_schema(DOMAIN)

_PERCENT = probatio.All(probatio.Coerce(int), probatio.Range(min=0, max=100))


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the action that moves both rails of a top-down/bottom-up shade at once."""
    _register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_POSITIONS,
        entity_domain=COVER_DOMAIN,
        schema={probatio.Optional(ATTR_TOP): _PERCENT, probatio.Optional(ATTR_BOTTOM): _PERCENT},
        func="async_set_positions",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PowerViewConfigEntry) -> bool:
    """Read the gateway's home, add its devices and entities, and start listening to it."""
    client = new_client(hass, entry.data[CONF_HOST])
    try:
        home = await client.get_home()
    except PowerViewError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": client.host},
        ) from err
    hub = PowerViewHub(hass, entry, client, home)
    entry.runtime_data = hub
    registry = dr.async_get(hass)
    # The gateway first, as each shade's device is connected through it.
    hub.gateway_device_id = registry.async_get_or_create(
        config_entry_id=entry.entry_id, **gateway_device(hub)
    ).id
    _remove_stale_devices(registry, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hub.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowerViewConfigEntry) -> bool:
    """Unload the entities; the entry stops the listening and polling itself."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: PowerViewConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a device only when the home no longer has it."""
    return not device.identifiers & _current_identifiers(entry.runtime_data)


def _current_identifiers(hub: PowerViewHub) -> set[tuple[str, str]]:
    return {gateway_identifier(hub)} | {
        shade_identifier(hub, shade_id) for shade_id in hub.home.shades}


@callback
def _remove_stale_devices(registry: dr.DeviceRegistry, entry: PowerViewConfigEntry) -> None:
    """Remove the devices of shades the home no longer has."""
    current = _current_identifiers(entry.runtime_data)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & current:
            registry.async_remove_device(device.id)
