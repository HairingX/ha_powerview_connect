"""Whether each gateway answers and reaches the internet, and whether the battery of each shade
that has one is low."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
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
    """Add a connection and an internet sensor for each gateway, and a low battery sensor for
    each shade not on mains power."""
    hub = entry.runtime_data
    sensors: list[BinarySensorEntity] = []
    for gateway in gateways(hub):
        sensors += [PowerViewGatewayConnection(hub, gateway), PowerViewGatewayInternet(hub, gateway)]
    sensors += [
        PowerViewLowBattery(hub, shade) for shade in hub.home.shades.values() if has_battery(shade)
    ]
    add_entities(hub, async_add_entities, sensors)


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


class PowerViewGatewayConnection(PowerViewGatewayEntity, BinarySensorEntity):
    """On while a gateway answers when asked of its state."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "connection"

    def __init__(self, hub: PowerViewHub, gateway: Gateway) -> None:
        """The connection sensor of `gateway`."""
        super().__init__(hub, gateway, "connection")
        self._update()

    def _update(self) -> None:
        # Always available: a gateway that does not answer is what it reports.
        self._attr_available = True
        self._attr_is_on = self.status is not None


class PowerViewGatewayInternet(PowerViewGatewayEntity, BinarySensorEntity):
    """On while a gateway reports it reaches the internet, which the app uses away from home."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "internet"

    def __init__(self, hub: PowerViewHub, gateway: Gateway) -> None:
        """The internet sensor of `gateway`."""
        super().__init__(hub, gateway, "internet")
        self._update()

    def _update(self) -> None:
        super()._update()
        self._attr_is_on = self.status.internet_connected if self.status else None
