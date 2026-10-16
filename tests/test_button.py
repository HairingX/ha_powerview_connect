"""Each shade's button that shows which shade it is."""

from __future__ import annotations

import pytest
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerview_connect.runtime import PowerViewRuntime

from .conftest import BOTTOM_UP, state

JOG = "button.living_room_patio_door_identify"


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: entity_id}, blocking=True)


async def test_every_shade_has_a_jog_button(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime
) -> None:
    registry = er.async_get(hass)
    buttons = [entity for entity in er.async_entries_for_config_entry(registry, config_entry.entry_id)
               if entity.domain == "button"]
    assert len(buttons) == len(loaded.hub.shades)
    jog = registry.async_get(JOG)
    assert jog is not None and jog.entity_category is EntityCategory.CONFIG
    assert state(hass, JOG).attributes["device_class"] == "identify"


async def test_the_jog_button_jogs_the_shade(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    await _press(hass, JOG)
    assert [(r.path, r.body) for r in gateway.requests if r.method == "PUT"] == [
        (f"/home/shades/{BOTTOM_UP}/motion", {"motion": "jog"})]


async def test_a_jog_the_gateway_refuses_is_an_error(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    gateway.command_errors[BOTTOM_UP] = 7
    with pytest.raises(HomeAssistantError, match="did not take the command"):
        await _press(hass, JOG)
