"""Whether each gateway answers and reaches the internet, and whether the battery of each shade
that has one is low."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import Gateway

from .entity import (
    Members,
    PowerViewGatewayEntity,
    PowerViewShadeEntity,
    askable_gateways,
    set_up_platform,
)
from .runtime import PowerViewConfigEntry, PowerViewRuntime

PARALLEL_UPDATES = 0


def _sensors(runtime: PowerViewRuntime, members: Members) -> Iterable[BinarySensorEntity]:
    sensors: list[BinarySensorEntity] = []
    for gateway in askable_gateways(runtime, members):
        sensors += [PowerViewGatewayConnection(runtime, gateway),
                    PowerViewGatewayInternet(runtime, gateway)]
    sensors += [PowerViewLowBattery(runtime, shade_id) for shade_id in sorted(members.shades)
                if runtime.hub.shade(shade_id).shade.has_battery]
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a connection and an internet sensor for each gateway, and a low battery sensor for
    each shade not on mains power."""
    set_up_platform(entry, async_add_entities, _sensors)


class PowerViewLowBattery(PowerViewShadeEntity, BinarySensorEntity):
    """On while the gateway reports a shade's battery low."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY

    def __init__(self, runtime: PowerViewRuntime, shade_id: int) -> None:
        """The low battery sensor of shade `shade_id`."""
        super().__init__(runtime, shade_id)
        self._attr_unique_id = f"{runtime.unique_id}_{shade_id}_battery_low"
        self._update()

    def _update(self) -> None:
        super()._update()
        self._attr_is_on = self.shade_state.shade.battery_low


class PowerViewGatewayConnection(PowerViewGatewayEntity, BinarySensorEntity):
    """On while a gateway answers when asked of its state."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "connection"

    def __init__(self, runtime: PowerViewRuntime, gateway: Gateway) -> None:
        """The connection sensor of `gateway`."""
        super().__init__(runtime, gateway, "connection")
        self._update()

    def _update(self) -> None:
        # Available while the gateway is known: not answering is what it reports.
        state = self.gateway_state
        self._attr_available = state is not None
        self._attr_is_on = None if state is None or state.reachable is None else state.reachable


class PowerViewGatewayInternet(PowerViewGatewayEntity, BinarySensorEntity):
    """On while a gateway reports it reaches the internet, which the app uses away from home."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "internet"

    def __init__(self, runtime: PowerViewRuntime, gateway: Gateway) -> None:
        """The internet sensor of `gateway`."""
        super().__init__(runtime, gateway, "internet")
        self._update()

    def _update(self) -> None:
        super()._update()
        state = self.gateway_state
        status = state.status if state else None
        self._attr_is_on = status.internet_connected if status else None
