"""Each shade's covers, as the library says a shade of its capabilities is controlled.

A top-down/bottom-up shade has two: "Top", its top rail (0 at the top, 100 fully down), and
"Bottom", its bottom rail (0 fully down, 100 fully up). A dual-overlapped shade has "Front" and
"Rear". A command sends only its own rail, and the shade keeps the other one where it is, so
commands from here, the PowerView app or a voice assistant never undo each other.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import CoverRole, CoverSpec, Rail

from .const import DOMAIN
from .entity import Members, PowerViewShadeEntity, set_up_platform
from .runtime import PowerViewConfigEntry, PowerViewRuntime, run_command

PARALLEL_UPDATES = 0

POSITION_FEATURES = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.SET_POSITION
    | CoverEntityFeature.STOP
)
TILT_FEATURES = (
    CoverEntityFeature.OPEN_TILT
    | CoverEntityFeature.CLOSE_TILT
    | CoverEntityFeature.SET_TILT_POSITION
    | CoverEntityFeature.STOP_TILT
)
_ONE_OF_TWO = frozenset({CoverRole.TOP, CoverRole.BOTTOM, CoverRole.FRONT, CoverRole.REAR})
"""Roles of a shade with two covers: each is named, and its unique id carries the role."""


def _covers(runtime: PowerViewRuntime, members: Members) -> Iterable[PowerViewCover]:
    for shade_id in sorted(members.shades):
        for cover in runtime.hub.shade(shade_id).covers:
            yield PowerViewCover(runtime, shade_id, cover)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the covers of each shade."""
    set_up_platform(entry, async_add_entities, _covers)


def _percent(openness: float | None) -> int | None:
    return None if openness is None else round(openness * 100)


class PowerViewCover(PowerViewShadeEntity, CoverEntity):
    """One cover of a shade, with the shade's vanes as its tilt where it has them."""

    def __init__(self, runtime: PowerViewRuntime, shade_id: int, cover: CoverSpec) -> None:
        """The cover `cover` of shade `shade_id`."""
        super().__init__(runtime, shade_id)
        self.cover = cover
        self._attr_device_class = (
            CoverDeviceClass.CURTAIN if cover.vertical else CoverDeviceClass.SHADE)
        features = CoverEntityFeature(0)
        if cover.rail is not None:
            features |= POSITION_FEATURES
        if cover.tilt or cover.rail is None:
            features |= TILT_FEATURES
        self._attr_supported_features = features
        key = str(cover.role) if cover.role in _ONE_OF_TWO else None
        self._attr_unique_id = f"{runtime.unique_id}_{shade_id}" + (f"_{key}" if key else "")
        if key is not None:
            self._attr_translation_key = key
        else:
            self._attr_name = None
        self._update()

    def _update(self) -> None:
        super()._update()
        state = self.shade_state
        cover = self.cover
        if cover.rail is not None:
            self._attr_current_cover_position = _percent(cover.openness(state.positions))
        if cover.tilt or cover.rail is None:
            self._attr_current_cover_tilt_position = _percent(
                cover.tilt_openness(state.positions))
        direction = cover.direction(state.directions)
        self._attr_is_closed = cover.closed(state.positions)
        self._attr_is_opening = direction > 0
        self._attr_is_closing = direction < 0
        target = cover.openness(state.targets) if cover.rail is not None else (
            cover.tilt_openness(state.targets))
        self._attr_extra_state_attributes = {
            "target_position": _percent(target) if state.moving else None}

    async def _move(self, percent: float) -> None:
        await run_command(self.hub.move_cover(self.shade_id, self.cover, percent / 100))

    async def _tilt(self, percent: float) -> None:
        await run_command(self.hub.tilt_cover(self.shade_id, self.cover, percent / 100))

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move this cover only."""
        await self._move(kwargs[ATTR_POSITION])

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open this cover."""
        await self._move(100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close this cover."""
        await self._move(0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the shade: every rail, as the gateway stops a whole shade."""
        await run_command(self.hub.stop(self.shade_id))

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Tilt the vanes only."""
        await self._tilt(kwargs[ATTR_TILT_POSITION])

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Tilt the vanes fully open."""
        await self._tilt(100)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Tilt the vanes closed."""
        await self._tilt(0)

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        """Stop the shade, as the gateway stops a whole shade."""
        await run_command(self.hub.stop(self.shade_id))

    async def async_set_positions(self, top: int | None = None, bottom: int | None = None) -> None:
        """Move the top and bottom rails of a top-down/bottom-up shade in one request.

        Raises:
            ServiceValidationError: the shade is not top-down/bottom-up, or no rail is given.
        """
        if self.cover.role not in (CoverRole.TOP, CoverRole.BOTTOM):
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
        await run_command(self.hub.move(self.shade_id, targets))
