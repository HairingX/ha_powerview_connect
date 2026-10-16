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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.typing import ConfigType
from powerview_connect import Change, GatewayChanged, HomeChanged, PowerViewError

from .const import ATTR_BOTTOM, ATTR_TOP, DOMAIN, SERVICE_SET_POSITIONS
from .entity import gateway_device, gateway_identifier, shade_device, shade_identifier
from .runtime import PowerViewConfigEntry, PowerViewRuntime, new_hub

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
    """Read the gateway's home, add its devices and entities, and start following it."""
    hub = new_hub(hass, entry, entry.data[CONF_HOST])
    try:
        await hub.load()
    except PowerViewError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": hub.host},
        ) from err
    runtime = PowerViewRuntime(hub, entry.unique_id or hub.host)
    entry.runtime_data = runtime
    registry = dr.async_get(hass)
    _register_gateways(registry, entry)
    _remove_stale_devices(registry, entry)
    # Devices follow the home before the platforms add entities for what was added to it.
    entry.async_on_unload(hub.subscribe(lambda change: _follow(hass, entry, change)))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _remove_lost_entities(hass, entry)
    entry.async_create_background_task(hass, hub.run(), f"{DOMAIN} {entry.title}")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowerViewConfigEntry) -> bool:
    """Unload the entities; Home Assistant cancels the hub's task with the entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: PowerViewConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a device only when the home no longer has it."""
    return not device.identifiers & _current_identifiers(entry.runtime_data)


def _current_identifiers(runtime: PowerViewRuntime) -> set[tuple[str, str]]:
    hub = runtime.hub
    return {gateway_identifier(runtime, gateway) for gateway in hub.home.gateways} | {
        gateway_identifier(runtime)} | {shade_identifier(runtime, shade_id) for shade_id in hub.shades}


@callback
def _register_gateways(registry: dr.DeviceRegistry, entry: PowerViewConfigEntry) -> None:
    """Register each gateway's device, the one the hub reaches first, as the others are
    connected through it."""
    runtime = entry.runtime_data
    hub = runtime.hub
    runtime.primary_device_id = registry.async_get_or_create(
        config_entry_id=entry.entry_id, **gateway_device(runtime, hub.gateway)).id
    for state in hub.gateways.values():
        gateway = state.gateway
        if gateway == hub.gateway:
            runtime.device_ids[gateway.serial] = runtime.primary_device_id
        else:
            runtime.device_ids[gateway.serial] = registry.async_get_or_create(
                config_entry_id=entry.entry_id, **gateway_device(runtime, gateway)).id


@callback
def _follow(hass: HomeAssistant, entry: PowerViewConfigEntry, change: Change) -> None:
    """Keep the devices as the home is: added, changed and removed shades and gateways."""
    runtime = entry.runtime_data
    registry = dr.async_get(hass)
    match change:
        case HomeChanged(_, diff):
            if diff.added_gateways or diff.changed_gateways:
                _register_gateways(registry, entry)
            for shade_id in diff.changed_shades:
                shade = runtime.hub.shade(shade_id).shade
                device = registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={shade_identifier(runtime, shade_id)})
                # A name the user gave the device is kept apart, and still shown.
                registry.async_update_device(
                    device.id, name=shade.name, sw_version=shade.firmware,
                    model=shade_device(runtime, shade).get("model"),
                    via_device_id=runtime.via_device_id(shade_id))
            if diff.removed_shades or diff.removed_gateways or diff.removed_scenes:
                _remove_stale_devices(registry, entry)
                _remove_scenes(hass, entry, diff.removed_scenes)
        case GatewayChanged(state) if state.status is not None:
            # A gateway is asked only once the home that lists it has given it a device.
            registry.async_update_device(
                runtime.device_ids[state.gateway.serial],
                hw_version=state.status.hardware_version, sw_version=state.status.firmware)
        case _:
            pass


@callback
def _remove_scenes(hass: HomeAssistant, entry: PowerViewConfigEntry, scene_ids: frozenset[int]) -> None:
    registry = er.async_get(hass)
    unique_ids = {f"{entry.runtime_data.unique_id}_scene_{scene_id}" for scene_id in scene_ids}
    for found in er.async_entries_for_config_entry(registry, entry.entry_id):
        if found.unique_id in unique_ids:
            registry.async_remove(found.entity_id)


@callback
def _remove_lost_entities(hass: HomeAssistant, entry: PowerViewConfigEntry) -> None:
    """Remove the entities this version no longer makes, so none is left unavailable."""
    registry = er.async_get(hass)
    for found in er.async_entries_for_config_entry(registry, entry.entry_id):
        if found.unique_id not in entry.runtime_data.unique_ids:
            registry.async_remove(found.entity_id)


@callback
def _remove_stale_devices(registry: dr.DeviceRegistry, entry: PowerViewConfigEntry) -> None:
    """Remove the devices of shades and gateways the home no longer has."""
    current = _current_identifiers(entry.runtime_data)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & current:
            registry.async_remove_device(device.id)
