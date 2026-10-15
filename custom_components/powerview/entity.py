"""Base entities for PowerView Gen 3."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import CAPABILITY_NAMES, DOMAIN, MANUFACTURER, signal_hub_availability, signal_shade_update
from .hub import PowerViewHub
from .model import ShadeInfo
from .motion import ShadeTracker


def hub_device_kwargs(hub: PowerViewHub) -> dict[str, Any]:
    """Gateway device fields (plain dict, usable for the device registry)."""
    gw = hub.gateway
    return {
        "identifiers": {(DOMAIN, hub.unique_id)},
        "manufacturer": MANUFACTURER,
        "name": gw.name if gw else "PowerView Gateway",
        "model": f"PowerView Gen 3 Gateway {gw.model}" if gw and gw.model else "PowerView Gen 3 Gateway",
        "sw_version": gw.firmware if gw else None,
        "serial_number": gw.serial if gw else None,
        "configuration_url": f"{hub.client.base_url}/home",
    }


def hub_device_info(hub: PowerViewHub) -> DeviceInfo:
    """Device info for the gateway."""
    return DeviceInfo(**hub_device_kwargs(hub))


class PowerViewEntity(Entity):
    """Common availability and dispatcher handling."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: PowerViewHub) -> None:
        """Initialise."""
        self.hub = hub

    @property
    def available(self) -> bool:
        """Gateway reachable."""
        return self.hub.available

    async def async_added_to_hass(self) -> None:
        """Listen for gateway availability."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_hub_availability(self.hub.entry.entry_id), self.async_write_ha_state
            )
        )


class PowerViewShadeEntity(PowerViewEntity):
    """An entity belonging to one shade."""

    def __init__(self, hub: PowerViewHub, shade: ShadeInfo) -> None:
        """Initialise."""
        super().__init__(hub)
        self.shade = shade
        cap = CAPABILITY_NAMES.get(shade.capabilities, f"capabilities {shade.capabilities}")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{hub.unique_id}_{shade.id}")},
            manufacturer=MANUFACTURER,
            name=shade.name,
            model=f"{cap} (type {shade.type})",
            sw_version=shade.firmware,
            serial_number=shade.serial,
            suggested_area=shade.room_name,
            via_device=(DOMAIN, hub.unique_id),
        )

    @property
    def tracker(self) -> ShadeTracker:
        """Return the motion tracker."""
        return self.hub.trackers[self.shade.id]

    @property
    def available(self) -> bool:
        """Gateway reachable and shade online."""
        return self.hub.available and self.tracker.online

    async def async_added_to_hass(self) -> None:
        """Listen for shade updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_shade_update(self.hub.entry.entry_id, self.shade.id), self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
