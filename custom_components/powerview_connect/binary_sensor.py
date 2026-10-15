"""Whether the battery of each shade that has one is low."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import BatteryStatus, Shade

from .entity import PowerViewShadeEntity, add_entities, has_battery
from .hub import PowerViewConfigEntry, PowerViewHub

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a low battery sensor for each shade not on mains power."""
    hub = entry.runtime_data
    add_entities(hub, async_add_entities, [
        PowerViewLowBattery(hub, shade) for shade in hub.home.shades.values() if has_battery(shade)
    ])


class PowerViewLowBattery(PowerViewShadeEntity, BinarySensorEntity):
    """On while the gateway reports a shade's battery low."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY

    def __init__(self, hub: PowerViewHub, shade: Shade) -> None:
        """The low battery sensor of `shade`."""
        super().__init__(hub, shade)
        self._attr_unique_id = f"{hub.unique_id}_{shade.id}_battery_low"
        self._update()

    def _update(self) -> None:
        super()._update()
        battery = self.hub.batteries[self.shade.id]
        self._attr_is_on = None if battery in (None, BatteryStatus.UNKNOWN) else (
            battery is BatteryStatus.LOW)
