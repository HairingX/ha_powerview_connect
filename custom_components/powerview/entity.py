"""The entities every platform builds on, and the devices they belong to."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from powerview_connect import Shade, ShadeTracker

from .const import DOMAIN, MANUFACTURER
from .hub import PowerViewHub


def gateway_identifier(hub: PowerViewHub) -> tuple[str, str]:
    """The device registry identifier of the gateway."""
    return (DOMAIN, hub.unique_id)


def shade_identifier(hub: PowerViewHub, shade_id: int) -> tuple[str, str]:
    """The device registry identifier of a shade."""
    return (DOMAIN, f"{hub.unique_id}_{shade_id}")


def gateway_device(hub: PowerViewHub) -> DeviceInfo:
    """The gateway as a device."""
    gateway = hub.gateway
    return DeviceInfo(
        identifiers={gateway_identifier(hub)},
        manufacturer=MANUFACTURER,
        name=gateway.name if gateway else "PowerView Gateway",
        model=f"PowerView Gen 3 Gateway {gateway.model}" if gateway and gateway.model
        else "PowerView Gen 3 Gateway",
        sw_version=gateway.firmware if gateway else None,
        serial_number=gateway.serial if gateway else None,
        configuration_url=f"{hub.client.base_url}/home",
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
        via_device_id=hub.gateway_device_id,
    )


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
