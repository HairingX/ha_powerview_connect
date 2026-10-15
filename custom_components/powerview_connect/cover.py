"""Each shade's rails as covers, and its vanes as their tilt.

A top-down/bottom-up shade has two: "Top", its top rail (0 at the top, 100 fully down), and
"Bottom", its bottom rail (0 fully down, 100 fully up). A dual-overlapped shade has "Front" and
"Rear". A command sends only its own rail, and the shade keeps the other one where it is, so
commands from here, the PowerView app or a voice assistant never undo each other. The shade's
own firmware stops a rail where it meets the other.
"""

from __future__ import annotations

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
from powerview_connect import Capabilities, Rail, Shade

from .const import DOMAIN
from .entity import PowerViewShadeEntity
from .hub import PowerViewConfigEntry, PowerViewHub

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
TOP_DOWN_BOTTOM_UP_KEYS = ("top", "bottom")

_TILTS = frozenset({
    Capabilities.BOTTOM_UP_TILT_90,
    Capabilities.BOTTOM_UP_TILT_180,
    Capabilities.VERTICAL_TILT_180,
})
_DUAL_OVERLAPPED = frozenset({
    Capabilities.DUAL_OVERLAPPED,
    Capabilities.DUAL_OVERLAPPED_TILT_90,
    Capabilities.DUAL_OVERLAPPED_TILT_180,
})
_VERTICAL = frozenset({Capabilities.VERTICAL, Capabilities.VERTICAL_TILT_180})


def covers_of(hub: PowerViewHub, shade: Shade) -> list[PowerViewCover]:
    """The covers of `shade`, by its capabilities as the Gen 3 API describes them."""
    capability = shade.capability
    device_class = (
        CoverDeviceClass.CURTAIN if capability in _VERTICAL else CoverDeviceClass.SHADE)
    match capability:
        case Capabilities.TOP_DOWN_BOTTOM_UP:
            return [PowerViewCover(hub, shade, Rail.SECONDARY, key="top"),
                    PowerViewCover(hub, shade, Rail.PRIMARY, key="bottom")]
        case Capabilities.TOP_DOWN:
            return [PowerViewCover(hub, shade, Rail.PRIMARY, inverted=True)]
        case Capabilities.TILT_ONLY_180:
            return [PowerViewCover(hub, shade, None, tilt=True)]
        case _ if capability in _DUAL_OVERLAPPED:
            return [
                PowerViewCover(hub, shade, Rail.PRIMARY, key="front",
                               tilt=capability is not Capabilities.DUAL_OVERLAPPED),
                PowerViewCover(hub, shade, Rail.SECONDARY, key="rear"),
            ]
        case _:
            return [PowerViewCover(hub, shade, Rail.PRIMARY, tilt=capability in _TILTS,
                                   device_class=device_class)]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the covers of each shade."""
    hub = entry.runtime_data
    async_add_entities(
        cover for shade in hub.home.shades.values() for cover in covers_of(hub, shade))


class PowerViewCover(PowerViewShadeEntity, CoverEntity):
    """One rail of a shade, with the shade's vanes as its tilt where it has them."""

    def __init__(
        self,
        hub: PowerViewHub,
        shade: Shade,
        rail: Rail | None,
        *,
        key: str | None = None,
        inverted: bool = False,
        tilt: bool = False,
        device_class: CoverDeviceClass = CoverDeviceClass.SHADE,
    ) -> None:
        """The cover of `rail`, None for vanes alone: one of two named by `key`, or the only one.

        Args:
            inverted: 100 is the rail's 0.0, as for a top-down shade, which opens downwards.
            tilt: the cover also tilts the shade's vanes.
        """
        super().__init__(hub, shade)
        self.rail = rail
        self._tilt = tilt
        self._inverted = inverted
        self._is_top_down_bottom_up = key in TOP_DOWN_BOTTOM_UP_KEYS
        self._attr_device_class = device_class
        features = CoverEntityFeature(0)
        if rail is not None:
            features |= POSITION_FEATURES
        if tilt:
            features |= TILT_FEATURES
        self._attr_supported_features = features
        self._attr_unique_id = f"{hub.unique_id}_{shade.id}" + (f"_{key}" if key else "")
        if key is not None:
            self._attr_translation_key = key
        else:
            self._attr_name = None
        self._update()

    def _percent(self, value: float | None, *, inverted: bool = False) -> int | None:
        if value is None:
            return None
        percent = round(value * 100)
        return 100 - percent if inverted else percent

    def _update(self) -> None:
        super()._update()
        tracker = self.tracker
        main = self.rail if self.rail is not None else Rail.TILT
        inverted = self._inverted and self.rail is not None
        if self.rail is not None:
            self._attr_current_cover_position = self._percent(
                tracker.current[self.rail], inverted=inverted)
        if self._tilt:
            self._attr_current_cover_tilt_position = self._percent(tracker.current[Rail.TILT])
        closed_at = self._percent(tracker.current[main], inverted=inverted)
        direction = tracker.direction(main) * (-1 if inverted else 1)
        self._attr_is_closed = None if closed_at is None else closed_at == 0
        self._attr_is_opening = direction > 0
        self._attr_is_closing = direction < 0
        self._attr_extra_state_attributes = {
            "target_position": self._percent(tracker.target[main], inverted=inverted)
            if tracker.moving else None,
        }

    async def _move(self, rail: Rail, percent: float) -> None:
        value = percent / 100
        if self._inverted and rail is self.rail:
            value = 1.0 - value
        await self.hub.async_move(self.shade.id, {rail: value})

    def _position_rail(self) -> Rail:
        assert self.rail is not None  # only offered where the cover has a rail
        return self.rail

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move this rail only."""
        await self._move(self._position_rail(), kwargs[ATTR_POSITION])

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Move this rail to 100."""
        await self._move(self._position_rail(), 100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Move this rail to 0."""
        await self._move(self._position_rail(), 0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the shade: every rail, as the gateway stops a whole shade."""
        await self.hub.async_stop(self.shade.id)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Tilt the vanes only."""
        await self._move(Rail.TILT, kwargs[ATTR_TILT_POSITION])

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Tilt the vanes fully open."""
        await self._move(Rail.TILT, 100)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Tilt the vanes closed."""
        await self._move(Rail.TILT, 0)

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        """Stop the shade, as the gateway stops a whole shade."""
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
