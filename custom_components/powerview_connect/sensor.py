"""The network each gateway is on, how well the gateway hears each shade, and the battery of each
shade that has one."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import BatteryStatus, Gateway

from .entity import (
    Members,
    PowerViewGatewayEntity,
    PowerViewShadeEntity,
    askable_gateways,
    set_up_platform,
)
from .runtime import PowerViewConfigEntry, PowerViewRuntime

PARALLEL_UPDATES = 0


def _sensors(runtime: PowerViewRuntime, members: Members) -> Iterable[SensorEntity]:
    sensors: list[SensorEntity] = [
        PowerViewGatewayNetwork(runtime, gateway) for gateway in askable_gateways(runtime, members)]
    for shade_id in sorted(members.shades):
        shade = runtime.hub.shade(shade_id).shade
        if shade.signal_strength is not None:
            sensors.append(PowerViewSignalStrength(runtime, shade_id))
        if shade.has_battery:
            sensors.append(PowerViewBatteryLevel(runtime, shade_id))
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a network sensor for each gateway, a signal strength sensor for each shade the gateway
    reports one for, and a battery sensor for each shade not on mains power."""
    set_up_platform(entry, async_add_entities, _sensors)


class PowerViewSignalStrength(PowerViewShadeEntity, SensorEntity):
    """The gateway's reception of a shade, read with the home and while the shade moves."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, runtime: PowerViewRuntime, shade_id: int) -> None:
        """The signal strength of shade `shade_id`."""
        super().__init__(runtime, shade_id)
        self._attr_unique_id = f"{runtime.unique_id}_{shade_id}_signal_strength"
        self._update()

    def _update(self) -> None:
        super()._update()
        self._attr_native_value = self.shade_state.shade.signal_strength


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

    def __init__(self, runtime: PowerViewRuntime, shade_id: int) -> None:
        """The battery level of shade `shade_id`."""
        super().__init__(runtime, shade_id)
        self._attr_unique_id = f"{runtime.unique_id}_{shade_id}_battery_level"
        self._update()

    def _update(self) -> None:
        super()._update()
        battery = self.shade_state.shade.battery
        self._attr_native_value = BATTERY_LEVELS.get(battery) if battery is not None else None


class PowerViewGatewayNetwork(PowerViewGatewayEntity, SensorEntity):
    """Whether a gateway is on a cable or on Wi-Fi."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["wired", "wifi"]
    _attr_translation_key = "network"

    def __init__(self, runtime: PowerViewRuntime, gateway: Gateway) -> None:
        """The network sensor of `gateway`."""
        super().__init__(runtime, gateway, "network")
        self._update()

    def _update(self) -> None:
        super()._update()
        state = self.gateway_state
        wifi = state.status.wifi if state and state.status else None
        self._attr_native_value = None if wifi is None else ("wifi" if wifi else "wired")
