"""The scenes stored on the gateway."""

from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from powerview_connect import Scene as GatewayScene

from .entity import PowerViewEntity, gateway_device
from .hub import PowerViewConfigEntry, PowerViewHub

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a scene for each scene on the gateway."""
    hub = entry.runtime_data
    async_add_entities(PowerViewScene(hub, scene) for scene in hub.home.scenes)


class PowerViewScene(PowerViewEntity, Scene):
    """A scene on the gateway, which moves its shades itself."""

    def __init__(self, hub: PowerViewHub, scene: GatewayScene) -> None:
        """The scene `scene`, named as on the gateway."""
        super().__init__(hub)
        self.scene_id = scene.id
        self._attr_name = scene.name
        self._attr_unique_id = f"{hub.unique_id}_scene_{scene.id}"
        self._attr_device_info = gateway_device(hub)

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        await self.hub.async_activate_scene(self.scene_id)
