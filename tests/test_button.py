"""Each shade's buttons: show which shade it is, and move it to its favorite position."""

from __future__ import annotations

import pytest
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from powerview_connect.testing import SimulatedGateway

from custom_components.powerview_connect.hub import PowerViewHub

from .conftest import BOTTOM_UP, P, state, until

JOG = "button.living_room_patio_door_identify"
FAVORITE = "button.living_room_patio_door_favorite_position"


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: entity_id}, blocking=True)


async def test_every_shade_has_a_jog_and_a_favorite_button(
    hass: HomeAssistant, loaded: PowerViewHub
) -> None:
    registry = er.async_get(hass)
    buttons = [entity for entity in er.async_entries_for_config_entry(registry, loaded.entry.entry_id)
               if entity.domain == "button"]
    assert len(buttons) == 2 * len(loaded.home.shades)
    jog = registry.async_get(JOG)
    assert jog is not None and jog.entity_category is EntityCategory.CONFIG
    assert state(hass, JOG).attributes["device_class"] == "identify"
    assert state(hass, FAVORITE).attributes["friendly_name"] == "Patio Door Favorite position"


async def test_the_jog_button_jogs_the_shade(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    await _press(hass, JOG)
    assert [(r.path, r.body) for r in gateway.requests if r.method == "PUT"] == [
        (f"/home/shades/{BOTTOM_UP}/motion", {"motion": "jog"})]


async def test_the_favorite_button_moves_the_shade_there_as_the_gateway_reports(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.shades[BOTTOM_UP].favorite = {P: 0.8}
    await _press(hass, FAVORITE)
    assert gateway.requests[-1].body == {"motion": "heart"}
    cover = "cover.living_room_patio_door"
    await until(lambda: state(hass, cover).state == "opening")
    assert state(hass, cover).attributes["target_position"] == 80
    gateway.finish(BOTTOM_UP)
    await until(lambda: state(hass, cover).attributes["current_position"] == 80)


@pytest.mark.parametrize("entity_id", [JOG, FAVORITE])
async def test_a_button_the_gateway_refuses_is_an_error(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway, entity_id: str
) -> None:
    gateway.command_errors[BOTTOM_UP] = 7
    with pytest.raises(HomeAssistantError, match="did not take the command"):
        await _press(hass, entity_id)
