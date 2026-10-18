"""The settings of each pleated shade's cover for retrying a stalled opening: the delay and the
threshold."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import CoverRole

from .entity import Members, PowerViewShadeEntity, set_up_platform
from .retry import retryable
from .runtime import PowerViewConfigEntry, PowerViewRuntime, RetrySettings

PARALLEL_UPDATES = 0


def _numbers(runtime: PowerViewRuntime, members: Members) -> Iterable[PowerViewRetryNumber]:
    for shade_id, role, cover_id in retryable(runtime, members):
        yield PowerViewRetryDelay(runtime, shade_id, role, cover_id)
        yield PowerViewRetryAbove(runtime, shade_id, role, cover_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the retry settings of each cover whose opening can be retried."""
    set_up_platform(entry, async_add_entities, _numbers)


class PowerViewRetryNumber(PowerViewShadeEntity, RestoreNumber):
    """One of a cover's settings for retrying a stalled opening, restored after a restart."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _key: str
    """The end of the setting's translation key and unique id."""

    def __init__(
        self, runtime: PowerViewRuntime, shade_id: int, role: CoverRole, cover_id: str
    ) -> None:
        """The setting of shade `shade_id`'s cover `role`, whose unique id is `cover_id`."""
        super().__init__(runtime, shade_id)
        self._role = role
        self._attr_translation_key = f"retry_stalled_opening_{self._key}"
        self._attr_unique_id = f"{cover_id}_retry_stalled_opening_{self._key}"
        self._update()

    def _value(self, settings: RetrySettings) -> float: ...

    def _store(self, settings: RetrySettings, value: float) -> None: ...

    async def async_added_to_hass(self) -> None:
        """Take the value it had before Home Assistant restarted, and follow the shade."""
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._store(self.runtime.retry(self.shade_id, self._role), last.native_value)
            self.runtime.apply_retry(self.shade_id, self._role)
        await super().async_added_to_hass()

    def _update(self) -> None:
        super()._update()
        self._attr_native_value = self._value(self.runtime.retry(self.shade_id, self._role))

    async def async_set_native_value(self, value: float) -> None:
        """Change the setting; a retry in progress keeps the value it started with."""
        self._store(self.runtime.retry(self.shade_id, self._role), value)
        self.runtime.apply_retry(self.shade_id, self._role)
        self._changed()


class PowerViewRetryDelay(PowerViewRetryNumber):
    """Seconds after each step of a retry, for the fabric to settle."""

    _key = "delay"
    _attr_native_min_value = 0
    _attr_native_max_value = 600
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def _value(self, settings: RetrySettings) -> float:
        return settings.delay

    def _store(self, settings: RetrySettings, value: float) -> None:
        settings.delay = value


class PowerViewRetryAbove(PowerViewRetryNumber):
    """The lowest position at which a stop of an opening counts as stalled."""

    _key = "above"
    _attr_native_min_value = 0
    _attr_native_max_value = 99
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    def _value(self, settings: RetrySettings) -> float:
        return settings.above

    def _store(self, settings: RetrySettings, value: float) -> None:
        settings.above = value
