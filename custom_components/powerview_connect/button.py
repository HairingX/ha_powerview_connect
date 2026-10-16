"""A button on each shade that shows which shade it is."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.button import ButtonEntity
from homeassistant.components.button.const import ButtonDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import Members, PowerViewShadeEntity, set_up_platform
from .runtime import PowerViewConfigEntry, PowerViewRuntime, run_command

PARALLEL_UPDATES = 0


def _buttons(runtime: PowerViewRuntime, members: Members) -> Iterable[PowerViewJog]:
    return [PowerViewJog(runtime, shade_id) for shade_id in sorted(members.shades)]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the jog button of each shade."""
    set_up_platform(entry, async_add_entities, _buttons)


class PowerViewJog(PowerViewShadeEntity, ButtonEntity):
    """Moves the shade briefly back and forth, to show which one it is."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: PowerViewRuntime, shade_id: int) -> None:
        """The jog button of shade `shade_id`."""
        super().__init__(runtime, shade_id)
        self._attr_unique_id = f"{runtime.unique_id}_{shade_id}_jog"
        self._update()

    async def async_press(self) -> None:
        """Jog the shade."""
        await run_command(self.hub.jog(self.shade_id))
