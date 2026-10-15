"""A button on each shade that shows which shade it is."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.components.button.const import ButtonDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import Shade

from .entity import PowerViewShadeEntity, add_entities
from .hub import PowerViewConfigEntry, PowerViewHub

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the jog button of each shade."""
    hub = entry.runtime_data
    add_entities(
        hub, async_add_entities, [PowerViewJog(hub, shade) for shade in hub.home.shades.values()]
    )


class PowerViewJog(PowerViewShadeEntity, ButtonEntity):
    """Moves the shade briefly back and forth, to show which one it is."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: PowerViewHub, shade: Shade) -> None:
        """The jog button of `shade`."""
        super().__init__(hub, shade)
        self._attr_unique_id = f"{hub.unique_id}_{shade.id}_jog"
        self._update()

    async def async_press(self) -> None:
        """Jog the shade."""
        await self.hub.async_jog(self.shade.id)

