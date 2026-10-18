"""A switch on each curtain that raises it the rest of the way when it stops short of fully open."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import Members, PowerViewShadeEntity, cover_unique_id, set_up_platform
from .runtime import PowerViewConfigEntry, PowerViewRuntime

PARALLEL_UPDATES = 0


def _switches(runtime: PowerViewRuntime, members: Members) -> Iterable[PowerViewRaiseWhenStuck]:
    for shade_id in sorted(members.shades):
        for cover in runtime.hub.shade(shade_id).covers:
            if cover.recoverable:
                yield PowerViewRaiseWhenStuck(runtime, shade_id,
                                              cover_unique_id(runtime, shade_id, cover.role))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switch of each shade with a cover that can be raised."""
    set_up_platform(entry, async_add_entities, _switches)


class PowerViewRaiseWhenStuck(PowerViewShadeEntity, SwitchEntity):
    """Whether the shade is raised the rest of the way when it stops short of fully open; off
    until turned on, and kept across restarts."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "raise_when_stuck"

    def __init__(self, runtime: PowerViewRuntime, shade_id: int, cover_id: str) -> None:
        """The switch of shade `shade_id`, whose cover has the unique id `cover_id`."""
        super().__init__(runtime, shade_id)
        self._attr_unique_id = f"{cover_id}_raise_when_stuck"
        self._update()

    def _update(self) -> None:
        super()._update()
        self._attr_is_on = self.hub.stall_recovery_enabled(self.shade_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Raise the shade when it stops short of fully open."""
        self.hub.set_stall_recovery(self.shade_id, True)
        await self.runtime.keep_raised()
        self._changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Leave the shade where it stops, and end a raise in progress."""
        self.hub.set_stall_recovery(self.shade_id, False)
        await self.runtime.keep_raised()
        self._changed()
