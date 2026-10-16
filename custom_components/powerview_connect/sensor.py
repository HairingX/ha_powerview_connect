"""The network each gateway is on, how well the gateway hears each shade, and the battery of each
shade that has one."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import BatteryStatus, Gateway, Shade

from .entity import (
    PowerViewGatewayEntity,
    PowerViewShadeEntity,
    add_entities,
    gateways,
    has_battery,
)
from .hub import PowerViewConfigEntry, PowerViewHub

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a network sensor for each gateway, a signal strength sensor for each shade the gateway
    reports one for, and a battery sensor for each shade not on mains power."""
    hub = entry.runtime_data
    sensors: list[SensorEntity] = [PowerViewGatewayNetwork(hub, gateway) for gateway in gateways(hub)]
    sensors += [
        PowerViewSignalStrength(hub, shade)
        for shade in hub.home.shades.values()
        if shade.signal_strength is not None
    ]
    sensors += [
        PowerViewBatteryLevel(hub, shade) for shade in hub.home.shades.values() if has_battery(shade)
    ]
    add_entities(hub, async_add_entities, sensors)


class PowerViewSignalStrength(PowerViewShadeEntity, SensorEntity):
    """The gateway's reception of a shade, read with the home and while the shade moves."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hub: PowerViewHub, shade: Shade) -> None:
        """The signal strength of `shade`."""
        super().__init__(hub, shade)
        self._attr_unique_id = f"{hub.unique_id}_{shade.id}_signal_strength"
        self._update()

    def _update(self) -> None:
        super()._update()
        self._attr_native_value = self.hub.signal_strengths[self.shade.id]


BATTERY_LEVELS: dict[BatteryStatus, str] = {
    BatteryStatus.LOW: "low",
    BatteryStatus.MEDIUM: "medium",
    BatteryStatus.HIGH: "high",
    BatteryStatus.PLUGGED_IN: "plugged_in",
}
"""The states of the battery level; an unknown status is shown as unknown."""


class PowerViewBatteryLevel(PowerViewShadeEntity, SensorEntity):
    """A shade's battery level, as the gateway reports it in steps."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(BATTERY_LEVELS.values())
    _attr_translation_key = "battery_level"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: PowerViewHub, shade: Shade) -> None:
        """The battery level of `shade`."""
        super().__init__(hub, shade)
        self._attr_unique_id = f"{hub.unique_id}_{shade.id}_battery_level"
        self._update()

    def _update(self) -> None:
        super()._update()
        battery = self.hub.batteries[self.shade.id]
        self._attr_native_value = BATTERY_LEVELS.get(battery) if battery is not None else None


class PowerViewGatewayNetwork(PowerViewGatewayEntity, SensorEntity):
    """Whether a gateway is on a cable or on Wi-Fi."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["wired", "wifi"]
    _attr_translation_key = "network"

    def __init__(self, hub: PowerViewHub, gateway: Gateway) -> None:
        """The network sensor of `gateway`."""
        super().__init__(hub, gateway, "network")
        self._update()

    def _update(self) -> None:
        super()._update()
        wifi = self.status.wifi if self.status else None
        self._attr_native_value = None if wifi is None else ("wifi" if wifi else "wired")
