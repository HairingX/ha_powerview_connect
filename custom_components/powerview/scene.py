"""Scenes stored on the PowerView gateway."""

from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PowerViewConfigEntry
from .entity import PowerViewEntity, hub_device_info
from .hub import PowerViewHub
from .model import SceneInfo

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create scene entities."""
    hub = entry.runtime_data
    async_add_entities(PowerViewScene(hub, scene) for scene in hub.home.scenes)


class PowerViewScene(PowerViewEntity, Scene):
    """A gateway scene. The gateway moves all member shades itself."""

    def __init__(self, hub: PowerViewHub, scene: SceneInfo) -> None:
        """Initialise."""
        super().__init__(hub)
        self._scene = scene
        self._attr_name = scene.name
        self._attr_unique_id = f"{hub.unique_id}_scene_{scene.id}"
        self._attr_device_info = hub_device_info(hub)

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        await self.hub.async_activate_scene(self._scene.id)
