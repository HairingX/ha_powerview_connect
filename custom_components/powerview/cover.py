"""Cover entities for PowerView Gen 3 shades.

Top-down/bottom-up shades (capabilities 7) get two entities, like the core integration:
  <shade> Top    -> secondary rail (0 = top rail at the top, 100 = top rail fully down)
  <shade> Bottom -> primary rail   (0 = bottom rail fully down, 100 = bottom rail fully up)
Every command sends ONLY the rail of that entity; the shade keeps the other rail as is,
so commands from HA, the app or Google never overwrite each other. The shade firmware
itself stops a rail where it meets the other one.
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

from . import PowerViewConfigEntry
from .const import CAPABILITY_TDBU, CAPABILITY_TOP_DOWN, DOMAIN
from .entity import PowerViewShadeEntity
from .hub import PowerViewHub
from .model import ShadeInfo

PARALLEL_UPDATES = 0
TILT_ONLY = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create cover entities."""
    hub = entry.runtime_data
    entities: list[PowerViewCover] = []
    for shade in hub.shades.values():
        if shade.capabilities == CAPABILITY_TDBU:
            entities.append(PowerViewCover(hub, shade, rail="secondary", key="top"))
            entities.append(PowerViewCover(hub, shade, rail="primary", key="bottom"))
        elif shade.capabilities == CAPABILITY_TOP_DOWN:
            entities.append(PowerViewCover(hub, shade, rail="primary", inverted=True))
        elif shade.capabilities == TILT_ONLY:
            entities.append(PowerViewCover(hub, shade, rail="tilt"))
        else:
            # Bottom-up and other types: primary rail only (tilt / dual-overlapped
            # extras are not exposed by this integration yet).
            entities.append(PowerViewCover(hub, shade, rail="primary"))
    async_add_entities(entities)


class PowerViewCover(PowerViewShadeEntity, CoverEntity):
    """One rail of a PowerView shade."""

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
        shade: ShadeInfo,
        *,
        rail: str,
        key: str | None = None,
        inverted: bool = False,
    ) -> None:
        """Initialise."""
        super().__init__(hub, shade)
        self._rail = rail
        self._inverted = inverted
        self._is_dual = key is not None
        self._attr_unique_id = f"{hub.unique_id}_{shade.id}" + (f"_{key}" if key else "")
        if key:
            self._attr_translation_key = key
        else:
            self._attr_name = None  # use the device (shade) name

    # ----- conversions ------------------------------------------------------

    def _to_ha(self, value: float | None) -> int | None:
        if value is None:
            return None
        pct = round(value * 100)
        return 100 - pct if self._inverted else pct

    def _from_ha(self, position: float) -> float:
        value = max(0.0, min(100.0, float(position))) / 100
        return 1.0 - value if self._inverted else value

    def _direction(self) -> int:
        direction = self.tracker.direction(self._rail)
        return -direction if self._inverted else direction

    # ----- state ------------------------------------------------------------

    @property
    def current_cover_position(self) -> int | None:
        """Live position (0-100)."""
        return self._to_ha(self.tracker.current.get(self._rail))

    @property
    def is_closed(self) -> bool | None:
        """Closed when at 0."""
        position = self.current_cover_position
        return None if position is None else position == 0

    @property
    def is_opening(self) -> bool:
        """Moving towards 100."""
        return self._direction() > 0

    @property
    def is_closing(self) -> bool:
        """Moving towards 0."""
        return self._direction() < 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the target so cards can show where the shade is heading."""
        tracker = self.tracker
        return {
            "target_position": self._to_ha(tracker.target.get(self._rail)) if tracker.moving else None,
            "moving": tracker.moving,
            "shade_id": self.shade.id,
        }

    # ----- commands ---------------------------------------------------------

    async def _move(self, position: float) -> None:
        await self.hub.async_move(self.shade.id, **{self._rail: self._from_ha(position)})

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
        """Stop the shade (both rails)."""
        await self.hub.async_stop(self.shade.id)

    async def async_set_positions(self, top: int | None = None, bottom: int | None = None) -> None:
        """Service powerview.set_positions: move both rails of a TDBU shade in one request."""
        if not self._is_dual:
            raise ServiceValidationError(
                f"{self.entity_id} is not a top-down/bottom-up shade",
                translation_domain=DOMAIN,
                translation_key="not_tdbu",
                translation_placeholders={"entity_id": self.entity_id},
            )
        if top is None and bottom is None:
            raise ServiceValidationError(
                "Give top and/or bottom", translation_domain=DOMAIN, translation_key="no_position"
            )
        await self.hub.async_move(
            self.shade.id,
            primary=None if bottom is None else bottom / 100,
            secondary=None if top is None else top / 100,
        )
