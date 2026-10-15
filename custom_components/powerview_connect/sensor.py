"""How well the gateway hears each shade."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import Shade

from .entity import PowerViewShadeEntity
from .hub import PowerViewConfigEntry, PowerViewHub

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a signal strength sensor for each shade the gateway reports one for."""
    hub = entry.runtime_data
    async_add_entities(
        PowerViewSignalStrength(hub, shade)
        for shade in hub.home.shades.values()
        if shade.signal_strength is not None
    )


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
