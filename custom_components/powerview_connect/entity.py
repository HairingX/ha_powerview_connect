"""The entities every platform builds on, and the devices they belong to."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import (
    Change,
    ConnectionChanged,
    Gateway,
    GatewayState,
    HomeChanged,
    Shade,
    ShadeState,
)

from .const import DOMAIN, MANUFACTURER
from .runtime import PowerViewConfigEntry, PowerViewRuntime


def gateway_identifier(runtime: PowerViewRuntime, gateway: Gateway | None = None) -> tuple[str, str]:
    """The device registry identifier of a gateway, the one the hub reaches by default."""
    if gateway is None or gateway == runtime.hub.gateway:
        return (DOMAIN, runtime.unique_id)
    return (DOMAIN, f"{runtime.unique_id}_gateway_{gateway.serial}")


def shade_identifier(runtime: PowerViewRuntime, shade_id: int) -> tuple[str, str]:
    """The device registry identifier of a shade."""
    return (DOMAIN, f"{runtime.unique_id}_{shade_id}")


def gateway_device(runtime: PowerViewRuntime, gateway: Gateway | None) -> DeviceInfo:
    """A gateway as a device: the one the hub reaches, or an auxiliary one connected through it."""
    if gateway is None:
        return DeviceInfo(
            identifiers={gateway_identifier(runtime)}, manufacturer=MANUFACTURER,
            name="PowerView Gateway", model="PowerView Gen 3 Gateway",
            configuration_url=f"{runtime.hub.base_url}/home",
        )
    state = runtime.hub.gateways.get(gateway.serial)
    status = state.status if state else None
    device = DeviceInfo(
        identifiers={gateway_identifier(runtime, gateway)},
        manufacturer=MANUFACTURER,
        name=gateway.name,
        model=f"PowerView Gen 3 Gateway {gateway.model}" if gateway.model
        else "PowerView Gen 3 Gateway",
        sw_version=gateway.firmware,
        hw_version=status.hardware_version if status else None,
        serial_number=gateway.serial,
    )
    if gateway == runtime.hub.gateway:
        device["configuration_url"] = f"{runtime.hub.base_url}/home"
    else:
        device["via_device_id"] = runtime.primary_device_id
    return device


def shade_device(runtime: PowerViewRuntime, shade: Shade) -> DeviceInfo:
    """A shade as a device, connected through the gateway that serves it."""
    return DeviceInfo(
        identifiers={shade_identifier(runtime, shade.id)},
        manufacturer=MANUFACTURER,
        name=shade.name,
        model=f"{shade.capability_name} (type {shade.type})",
        sw_version=shade.firmware,
        serial_number=shade.serial,
        suggested_area=shade.room_name,
        via_device_id=runtime.via_device_id(shade.id),
    )


@dataclass(frozen=True, slots=True)
class Members:
    """Which shades, scenes and gateways a platform is to add entities for."""

    shades: frozenset[int]
    scenes: frozenset[int]
    gateways: frozenset[str]


type Make = Callable[[PowerViewRuntime, Members], Iterable[Entity]]


def add_entities(
    runtime: PowerViewRuntime, async_add_entities: AddConfigEntryEntitiesCallback,
    entities: Iterable[Entity],
) -> None:
    """Add `entities`, noting their unique ids as ones the entry still has."""
    made = list(entities)
    runtime.unique_ids.update(entity.unique_id for entity in made if entity.unique_id)
    async_add_entities(made)


def set_up_platform(
    entry: PowerViewConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback, make: Make
) -> None:
    """Add a platform's entities for the home, and for what is added to it later."""
    runtime = entry.runtime_data
    hub = runtime.hub
    add_entities(runtime, async_add_entities, make(runtime, Members(
        frozenset(hub.shades), frozenset(scene.id for scene in hub.home.scenes),
        frozenset(hub.gateways))))

    @callback
    def added(change: Change) -> None:
        if isinstance(change, HomeChanged):
            diff = change.diff
            members = Members(diff.added_shades, diff.added_scenes, diff.added_gateways)
            if members.shades or members.scenes or members.gateways:
                add_entities(runtime, async_add_entities, make(runtime, members))

    entry.async_on_unload(hub.subscribe(added))


class PowerViewEntity(Entity):
    """An entity of the home, available while the primary gateway answers."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: PowerViewRuntime) -> None:
        """An entity of `runtime`'s home."""
        self.runtime = runtime
        self.hub = runtime.hub
        self._attr_available = self.hub.available

    async def async_added_to_hass(self) -> None:
        """Follow the connection to the gateway."""
        self.async_on_remove(self.hub.subscribe(self._on_change))
        self._update()

    @callback
    def _on_change(self, change: Change) -> None:
        if isinstance(change, ConnectionChanged):
            self._changed()

    def _update(self) -> None:
        self._attr_available = self.hub.available

    @callback
    def _changed(self, *_: object) -> None:
        self._update()
        self.async_write_ha_state()


class PowerViewShadeEntity(PowerViewEntity):
    """An entity of one shade, available while the gateway answers and the shade is online."""

    def __init__(self, runtime: PowerViewRuntime, shade_id: int) -> None:
        """An entity of shade `shade_id`."""
        self.shade_id = shade_id
        self.shade_state = runtime.hub.shade(shade_id)
        """The shade's state as last heard; kept once the home no longer has the shade."""
        super().__init__(runtime)
        self._attr_device_info = shade_device(runtime, self.shade_state.shade)

    async def async_added_to_hass(self) -> None:
        """Follow the shade, and the connection to the gateway."""
        self.async_on_remove(self.hub.subscribe_shade(self.shade_id, self._shade_changed))
        await super().async_added_to_hass()

    @callback
    def _shade_changed(self, state: ShadeState) -> None:
        self.shade_state = state
        self._changed()

    def _update(self) -> None:
        self._attr_available = (self.hub.available and self.shade_state.online
                                and self.shade_id in self.hub.home.shades)


class PowerViewGatewayEntity(PowerViewEntity):
    """An entity of one gateway, kept current from what it reports of itself."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: PowerViewRuntime, gateway: Gateway, key: str) -> None:
        """The `key` entity of `gateway`."""
        super().__init__(runtime)
        self.serial = gateway.serial
        self._attr_unique_id = f"{runtime.unique_id}_gateway_{gateway.serial}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={gateway_identifier(runtime, gateway)})

    @property
    def gateway_state(self) -> GatewayState | None:
        """What the hub knows of the gateway, None once the home no longer has it."""
        return self.hub.gateways.get(self.serial)

    async def async_added_to_hass(self) -> None:
        """Follow what the gateway reports."""
        self.async_on_remove(self.hub.subscribe_gateway(self.serial, self._changed))
        await super().async_added_to_hass()

    def _update(self) -> None:
        state = self.gateway_state
        self._attr_available = state is not None and state.reachable is True


def askable_gateways(runtime: PowerViewRuntime, members: Members) -> list[Gateway]:
    """The gateways among `members` that can be asked of their state."""
    gateways = runtime.hub.gateways
    return [gateways[serial].gateway for serial in sorted(members.gateways)
            if serial in gateways and gateways[serial].askable]
