"""The scenes stored on the gateway."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import Members, PowerViewEntity, gateway_device, set_up_platform
from .runtime import PowerViewConfigEntry, PowerViewRuntime, run_command

PARALLEL_UPDATES = 0


def _scenes(runtime: PowerViewRuntime, members: Members) -> Iterable[PowerViewScene]:
    return [PowerViewScene(runtime, scene.id, scene.name)
            for scene in runtime.hub.home.scenes if scene.id in members.scenes]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerViewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a scene for each scene on the gateway."""
    set_up_platform(entry, async_add_entities, _scenes)


class PowerViewScene(PowerViewEntity, Scene):
    """A scene on the gateway, which moves its shades itself."""

    def __init__(self, runtime: PowerViewRuntime, scene_id: int, name: str) -> None:
        """The scene `scene_id`, named as on the gateway."""
        super().__init__(runtime)
        self.scene_id = scene_id
        self._attr_name = name
        self._attr_unique_id = f"{runtime.unique_id}_scene_{scene_id}"
        self._attr_device_info = gateway_device(runtime, runtime.hub.gateway)

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        await run_command(self.hub.activate_scene(self.scene_id))
