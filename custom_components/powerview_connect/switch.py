"""A switch on each pleated shade's cover that retries its opening in steps when it stalls."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from powerview_connect import CoverRole

from .entity import Members, PowerViewShadeEntity, set_up_platform
from .retry import retryable
from .runtime import PowerViewConfigEntry, PowerViewRuntime

PARALLEL_UPDATES = 0


def _switches(runtime: PowerViewRuntime, members: Members) -> Iterable[PowerViewRetrySwitch]:
    return [PowerViewRetrySwitch(runtime, shade_id, role, cover_id)
            for shade_id, role, cover_id in retryable(runtime, members)]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switch of each cover whose opening can be retried."""
    set_up_platform(entry, async_add_entities, _switches)


# SwitchEntity and RestoreEntity declare four of Entity's attributes differently; Home
# Assistant's own type check accepts the pair, and a strict one cannot be satisfied otherwise.
class PowerViewRetrySwitch(PowerViewShadeEntity, SwitchEntity, RestoreEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """Whether a stalled opening of the cover is retried; off until turned on, and restored."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "retry_stalled_opening"

    def __init__(
        self, runtime: PowerViewRuntime, shade_id: int, role: CoverRole, cover_id: str
    ) -> None:
        """The switch of shade `shade_id`'s cover `role`, whose unique id is `cover_id`."""
        super().__init__(runtime, shade_id)
        self._role = role
        self._attr_unique_id = f"{cover_id}_retry_stalled_opening"
        self._update()

    async def async_added_to_hass(self) -> None:
        """Turn the retry on again where it was on, and follow the shade."""
        last = await self.async_get_last_state()
        self._set(last is not None and last.state == STATE_ON)
        await super().async_added_to_hass()

    async def async_will_remove_from_hass(self) -> None:
        """Stop retrying the shade while the switch is disabled or removed."""
        self._set(False)
        await super().async_will_remove_from_hass()

    def _set(self, on: bool) -> None:
        self.runtime.retry(self.shade_id, self._role).on = on
        self.runtime.apply_retry(self.shade_id, self._role)

    def _update(self) -> None:
        super()._update()
        self._attr_is_on = self.runtime.retry(self.shade_id, self._role).on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Retry the shade's opening in steps when it stalls."""
        self._set(True)
        self._changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Leave the shade where it stalls, and end a retry in progress."""
        self._set(False)
        self._changed()
