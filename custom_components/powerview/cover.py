"""Each shade's rails as covers.

A top-down/bottom-up shade has two: "Top", its top rail (0 at the top, 100 fully down), and
"Bottom", its bottom rail (0 fully down, 100 fully up). A command sends only its own rail, and
the shade keeps the other one where it is, so commands from here, the PowerView app or a voice
assistant never undo each other. The shade's own firmware stops a rail where it meets the other.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import Capabilities, Rail, Shade

from .const import DOMAIN
from .entity import PowerViewShadeEntity
from .hub import PowerViewConfigEntry, PowerViewHub

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a cover for each rail of each shade."""
    hub = entry.runtime_data
    covers: list[PowerViewCover] = []
    for shade in hub.home.shades.values():
        match shade.capability:
            case Capabilities.TOP_DOWN_BOTTOM_UP:
                covers.append(PowerViewCover(hub, shade, Rail.SECONDARY, key="top"))
                covers.append(PowerViewCover(hub, shade, Rail.PRIMARY, key="bottom"))
            case Capabilities.TOP_DOWN:
                covers.append(PowerViewCover(hub, shade, Rail.PRIMARY, inverted=True))
            case Capabilities.TILT_ONLY_180:
                covers.append(PowerViewCover(hub, shade, Rail.TILT))
            case _:
                covers.append(PowerViewCover(hub, shade, Rail.PRIMARY))
    async_add_entities(covers)


class PowerViewCover(PowerViewShadeEntity, CoverEntity):
    """One rail of a shade."""

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        hub: PowerViewHub,
        shade: Shade,
        rail: Rail,
        *,
        key: str | None = None,
        inverted: bool = False,
    ) -> None:
        """The cover of `rail`: one of two named by `key`, or the shade's only one.

        Args:
            inverted: 100 is the rail's 0.0, as for a top-down shade, which opens downwards.
        """
        super().__init__(hub, shade)
        self.rail = rail
        self._inverted = inverted
        self._is_top_down_bottom_up = key is not None
        self._attr_unique_id = f"{hub.unique_id}_{shade.id}" + (f"_{key}" if key else "")
        if key is not None:
            self._attr_translation_key = key
        else:
            self._attr_name = None
        self._update()

    def _percent(self, value: float | None) -> int | None:
        if value is None:
            return None
        percent = round(value * 100)
        return 100 - percent if self._inverted else percent

    def _fraction(self, percent: float) -> float:
        value = percent / 100
        return 1.0 - value if self._inverted else value

    def _update(self) -> None:
        super()._update()
        tracker = self.tracker
        position = self._percent(tracker.current[self.rail])
        direction = tracker.direction(self.rail) * (-1 if self._inverted else 1)
        self._attr_current_cover_position = position
        self._attr_is_closed = None if position is None else position == 0
        self._attr_is_opening = direction > 0
        self._attr_is_closing = direction < 0
        self._attr_extra_state_attributes = {
            "target_position": self._percent(tracker.target[self.rail]) if tracker.moving
            else None,
        }

    async def _move(self, percent: float) -> None:
        await self.hub.async_move(self.shade.id, {self.rail: self._fraction(percent)})

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move this rail only."""
        await self._move(kwargs[ATTR_POSITION])

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Move this rail to 100."""
        await self._move(100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Move this rail to 0."""
        await self._move(0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the shade: both rails, as the gateway stops a whole shade."""
        await self.hub.async_stop(self.shade.id)

    async def async_set_positions(self, top: int | None = None, bottom: int | None = None) -> None:
        """Move the top and bottom rails of a top-down/bottom-up shade in one request.

        Raises:
            ServiceValidationError: the shade is not top-down/bottom-up, or no rail is given.
        """
        if not self._is_top_down_bottom_up:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_top_down_bottom_up",
                translation_placeholders={"entity_id": self.entity_id},
            )
        targets: dict[Rail, float] = {}
        if bottom is not None:
            targets[Rail.PRIMARY] = bottom / 100
        if top is not None:
            targets[Rail.SECONDARY] = top / 100
        if not targets:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_position")
        await self.hub.async_move(self.shade.id, targets)
