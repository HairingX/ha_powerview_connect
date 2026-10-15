"""Buttons on each shade: show which shade it is, and move it to its favorite position."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.components.button.const import ButtonDeviceClass
from homeassistant.const import EntityCategory
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
    """Add the jog and favorite buttons of each shade."""
    hub = entry.runtime_data
    buttons: list[ButtonEntity] = []
    for shade in hub.home.shades.values():
        buttons += [PowerViewJog(hub, shade), PowerViewFavorite(hub, shade)]
    async_add_entities(buttons)


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


class PowerViewFavorite(PowerViewShadeEntity, ButtonEntity):
    """Moves the shade to the favorite position stored in it."""

    _attr_translation_key = "favorite"

    def __init__(self, hub: PowerViewHub, shade: Shade) -> None:
        """The favorite button of `shade`."""
        super().__init__(hub, shade)
        self._attr_unique_id = f"{hub.unique_id}_{shade.id}_favorite"
        self._update()

    async def async_press(self) -> None:
        """Move the shade to its favorite position."""
        await self.hub.async_move_to_favorite(self.shade.id)
