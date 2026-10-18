"""The setting of each pleated shade's cover for retrying a stalled opening: how far open a stop
must be."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import CoverRole

from .entity import Members, PowerViewShadeEntity, set_up_platform
from .retry import retryable
from .runtime import PowerViewConfigEntry, PowerViewRuntime

PARALLEL_UPDATES = 0


def _numbers(runtime: PowerViewRuntime, members: Members) -> Iterable[PowerViewRetryMinOpenness]:
    return [PowerViewRetryMinOpenness(runtime, shade_id, role, cover_id)
            for shade_id, role, cover_id in retryable(runtime, members)]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the retry setting of each cover whose opening can be retried."""
    set_up_platform(entry, async_add_entities, _numbers)


class PowerViewRetryMinOpenness(PowerViewShadeEntity, RestoreNumber):
    """How far open, in percent, an opening that stops must be to count as stalled; restored
    after a restart."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_translation_key = "retry_stalled_opening_min_openness"
    _attr_native_min_value = 0
    _attr_native_max_value = 99
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self, runtime: PowerViewRuntime, shade_id: int, role: CoverRole, cover_id: str
    ) -> None:
        """The setting of shade `shade_id`'s cover `role`, whose unique id is `cover_id`."""
        super().__init__(runtime, shade_id)
        self._role = role
        self._attr_unique_id = f"{cover_id}_retry_stalled_opening_min_openness"
        self._update()

    async def async_added_to_hass(self) -> None:
        """Take the value it had before Home Assistant restarted, and follow the shade."""
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self.runtime.retry(self.shade_id, self._role).min_openness = last.native_value
            self.runtime.apply_retry(self.shade_id, self._role)
        await super().async_added_to_hass()

    def _update(self) -> None:
        super()._update()
        self._attr_native_value = self.runtime.retry(self.shade_id, self._role).min_openness

    async def async_set_native_value(self, value: float) -> None:
        """Change the setting; a retry in progress keeps the value it started with."""
        self.runtime.retry(self.shade_id, self._role).min_openness = value
        self.runtime.apply_retry(self.shade_id, self._role)
        self._changed()
