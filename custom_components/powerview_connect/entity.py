"""The entities every platform builds on, and the devices they belong to."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import Gateway, GatewayStatus, Shade, ShadeTracker

from .const import DOMAIN, MANUFACTURER
from .hub import PowerViewHub


def gateway_identifier(hub: PowerViewHub, gateway: Gateway | None = None) -> tuple[str, str]:
    """The device registry identifier of a gateway, the primary one by default."""
    if gateway is None or gateway == hub.gateway:
        return (DOMAIN, hub.unique_id)
    return (DOMAIN, f"{hub.unique_id}_gateway_{gateway.serial}")


def shade_identifier(hub: PowerViewHub, shade_id: int) -> tuple[str, str]:
    """The device registry identifier of a shade."""
    return (DOMAIN, f"{hub.unique_id}_{shade_id}")


def gateway_device(hub: PowerViewHub) -> DeviceInfo:
    """The primary gateway as a device."""
    gateway = hub.gateway
    if gateway is None:
        return DeviceInfo(
            identifiers={gateway_identifier(hub)},
            manufacturer=MANUFACTURER,
            name="PowerView Gateway",
            model="PowerView Gen 3 Gateway",
            configuration_url=f"{hub.client.base_url}/home",
        )
    device = _gateway_details(hub, gateway)
    device["configuration_url"] = f"{hub.client.base_url}/home"
    return device


def auxiliary_gateway_device(hub: PowerViewHub, gateway: Gateway) -> DeviceInfo:
    """An auxiliary gateway as a device, connected through the primary gateway."""
    device = _gateway_details(hub, gateway)
    device["via_device_id"] = hub.gateway_device_id
    return device


def _gateway_details(hub: PowerViewHub, gateway: Gateway) -> DeviceInfo:
    status = hub.gateway_states.get(gateway.serial)
    return DeviceInfo(
        identifiers={gateway_identifier(hub, gateway)},
        manufacturer=MANUFACTURER,
        name=gateway.name,
        model=f"PowerView Gen 3 Gateway {gateway.model}" if gateway.model
        else "PowerView Gen 3 Gateway",
        sw_version=gateway.firmware,
        hw_version=status.hardware_version if status else None,
        serial_number=gateway.serial,
    )


def shade_device(hub: PowerViewHub, shade: Shade) -> DeviceInfo:
    """A shade as a device, connected through the gateway."""
    capability = shade.capability
    kind = capability.name.replace("_", " ").title() if capability is not None else (
        f"Capabilities {shade.capabilities}")
    return DeviceInfo(
        identifiers={shade_identifier(hub, shade.id)},
        manufacturer=MANUFACTURER,
        name=shade.name,
        model=f"{kind} (type {shade.type})",
        sw_version=shade.firmware,
        serial_number=shade.serial,
        suggested_area=shade.room_name,
        via_device_id=hub.via_device_id(shade.id),
    )


def add_entities(
    hub: PowerViewHub, async_add_entities: AddConfigEntryEntitiesCallback,
    entities: Iterable[Entity],
) -> None:
    """Add `entities`, noting their unique ids as ones the entry still has."""
    made = list(entities)
    hub.unique_ids.update(entity.unique_id for entity in made if entity.unique_id)
    async_add_entities(made)


def has_battery(shade: Shade) -> bool:
    """Whether the shade reports a power type other than mains power, so it has a battery."""
    return shade.power_type is not None and not shade.hard_wired


class PowerViewEntity(Entity):
    """An entity of the gateway, available while the gateway answers."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: PowerViewHub) -> None:
        """An entity of `hub`'s gateway."""
        self.hub = hub
        self._attr_available = hub.available

    async def async_added_to_hass(self) -> None:
        """Follow the gateway's availability."""
        self.async_on_remove(self.hub.async_listen(None, self._changed))

    def _update(self) -> None:
        self._attr_available = self.hub.available

    @callback
    def _changed(self) -> None:
        self._update()
        self.async_write_ha_state()


class PowerViewShadeEntity(PowerViewEntity):
    """An entity of one shade, available while the gateway answers and the shade is online."""

    def __init__(self, hub: PowerViewHub, shade: Shade) -> None:
        """An entity of `shade`."""
        super().__init__(hub)
        self.shade = shade
        self._attr_device_info = shade_device(hub, shade)

    @property
    def tracker(self) -> ShadeTracker:
        """The shade's motion."""
        return self.hub.trackers[self.shade.id]

    async def async_added_to_hass(self) -> None:
        """Follow the shade, and the gateway's availability."""
        await super().async_added_to_hass()
        self.async_on_remove(self.hub.async_listen(self.shade.id, self._changed))
        self._update()

    def _update(self) -> None:
        self._attr_available = self.hub.available and self.tracker.online


class PowerViewGatewayEntity(PowerViewEntity):
    """An entity of one gateway, kept current from what it reports of itself."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: PowerViewHub, gateway: Gateway, key: str) -> None:
        """The `key` entity of `gateway`."""
        super().__init__(hub)
        self.gateway = gateway
        self._attr_unique_id = f"{hub.unique_id}_gateway_{gateway.serial}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={gateway_identifier(hub, gateway)})

    @property
    def status(self) -> GatewayStatus | None:
        """What the gateway last reported of itself; None while it does not answer."""
        return self.hub.gateway_states[self.gateway.serial]

    async def async_added_to_hass(self) -> None:
        """Follow what the gateway reports."""
        await super().async_added_to_hass()
        self.async_on_remove(self.hub.async_listen(self.gateway.serial, self._changed))
        self._update()

    def _update(self) -> None:
        self._attr_available = self.status is not None


def gateways(hub: PowerViewHub) -> list[Gateway]:
    """The gateways of the home that can be asked of their state."""
    return [gateway for gateway in hub.home.gateways if gateway.serial in hub.gateway_clients]
