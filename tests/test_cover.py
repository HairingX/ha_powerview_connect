"""Covers: one for each rail, moved one rail at a time, and followed while they move."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    DOMAIN as COVER_DOMAIN,
    CoverState,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    SERVICE_STOP_COVER,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from powerview_connect import PowerViewClient
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.powerview_connect.const import DOMAIN, SERVICE_SET_POSITIONS
from custom_components.powerview_connect.hub import PowerViewHub

from .conftest import BOTTOM_UP, TDBU, FakeClock, P, S, state, until

TOP = "cover.living_room_kitchen_window_top"
BOTTOM = "cover.living_room_kitchen_window_bottom"
BOTTOM_UP_COVER = "cover.living_room_patio_door"
TOP_DOWN_COVER = "cover.bedroom_skylight"
TILT_COVER = "cover.bedroom_blind"


def _position(hass: HomeAssistant, entity_id: str) -> object:
    return state(hass, entity_id).attributes.get(ATTR_CURRENT_POSITION)


def _moves(gateway: SimulatedGateway) -> list[tuple[str, object]]:
    return [(request.query["ids"], request.body) for request in gateway.requests
            if request.path == "/home/shades/positions"]


async def _call(hass: HomeAssistant, service: str, entity_id: str, **data: Any) -> None:
    await hass.services.async_call(
        COVER_DOMAIN, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


async def _poll(hass: HomeAssistant, clock: FakeClock, seconds: float = 1.0) -> None:
    """Let a second pass, so a moving shade is read."""
    clock.advance(seconds)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_each_rail_is_a_cover_at_its_position(
    hass: HomeAssistant, loaded: PowerViewHub
) -> None:
    assert _position(hass, TOP) == 71
    assert state(hass, TOP).state == CoverState.OPEN
    assert _position(hass, BOTTOM) == 0
    assert state(hass, BOTTOM).state == CoverState.CLOSED
    assert _position(hass, BOTTOM_UP_COVER) == 40
    # A top-down shade opens downwards: its rail at 0.25 is 75 % closed.
    assert _position(hass, TOP_DOWN_COVER) == 75
    assert _position(hass, TILT_COVER) == 50
    assert state(hass, TOP).attributes["target_position"] is None
    assert state(hass, TOP).attributes["device_class"] == "shade"


@pytest.mark.parametrize(
    ("entity_id", "service", "data", "sent"),
    [
        (TOP, SERVICE_SET_COVER_POSITION, {ATTR_POSITION: 50}, {"secondary": 0.5}),
        (BOTTOM, SERVICE_OPEN_COVER, {}, {"primary": 1.0}),
        (BOTTOM_UP_COVER, SERVICE_CLOSE_COVER, {}, {"primary": 0.0}),
        (TOP_DOWN_COVER, SERVICE_SET_COVER_POSITION, {ATTR_POSITION: 100}, {"primary": 0.0}),
        (TILT_COVER, SERVICE_SET_COVER_POSITION, {ATTR_POSITION: 30}, {"tilt": 0.3}),
    ],
)
async def test_a_command_sends_only_its_own_rail(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway,
    entity_id: str, service: str, data: dict[str, Any], sent: dict[str, float],
) -> None:
    await _call(hass, service, entity_id, **data)
    assert [body for _, body in _moves(gateway)] == [{"positions": sent}]


async def test_top_and_bottom_commands_back_to_back_both_take_effect(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    """Neither command carries the other rail, so neither can undo the other."""
    await _call(hass, SERVICE_SET_COVER_POSITION, BOTTOM, **{ATTR_POSITION: 20})
    await _call(hass, SERVICE_SET_COVER_POSITION, TOP, **{ATTR_POSITION: 50})
    assert _moves(gateway) == [
        (str(TDBU), {"positions": {"primary": 0.2}}),
        (str(TDBU), {"positions": {"secondary": 0.5}}),
    ]
    gateway.finish(TDBU)
    await until(lambda: _position(hass, TOP) == 50 and _position(hass, BOTTOM) == 20)


async def test_a_move_from_any_source_is_shown_opening_or_closing_and_followed_live(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway, clock: FakeClock
) -> None:
    """The PowerView app, another client of the gateway, moves the shade; the gateway reports
    it, and the shade is read while it moves."""
    app = PowerViewClient(async_get_clientsession(hass), gateway.host)
    await app.set_positions([BOTTOM_UP], primary=0.9)
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == CoverState.OPENING)
    assert state(hass, BOTTOM_UP_COVER).attributes["target_position"] == 90
    gateway.move(BOTTOM_UP, {P: 0.6})
    await _poll(hass, clock)
    assert _position(hass, BOTTOM_UP_COVER) == 60
    assert state(hass, BOTTOM_UP_COVER).state == CoverState.OPENING
    gateway.finish(BOTTOM_UP)
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == CoverState.OPEN)
    assert _position(hass, BOTTOM_UP_COVER) == 90
    assert state(hass, BOTTOM_UP_COVER).attributes["target_position"] is None


async def test_a_top_down_shade_closing_its_rail_is_shown_opening(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    await _call(hass, SERVICE_OPEN_COVER, TOP_DOWN_COVER)
    assert state(hass, TOP_DOWN_COVER).state == CoverState.OPENING
    assert state(hass, TOP_DOWN_COVER).attributes["target_position"] == 100


async def test_a_move_ends_when_the_target_is_reached_and_still(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway, clock: FakeClock
) -> None:
    """Even when motion-stopped never comes."""
    await _call(hass, SERVICE_CLOSE_COVER, BOTTOM_UP_COVER)
    assert state(hass, BOTTOM_UP_COVER).state == CoverState.CLOSING
    gateway.move(BOTTOM_UP, {P: 0.2})
    await _poll(hass, clock)
    gateway.move(BOTTOM_UP, {P: 0.0})
    await _poll(hass, clock)
    assert loaded.trackers[BOTTOM_UP].moving
    assert state(hass, BOTTOM_UP_COVER).state == CoverState.CLOSED
    await _poll(hass, clock, 2)
    assert not loaded.trackers[BOTTOM_UP].moving
    requests = len(gateway.requests)
    await _poll(hass, clock)
    assert len(gateway.requests) == requests, "a shade standing still is read"


async def test_the_shade_stopping_a_rail_where_it_meets_the_other_ends_the_move(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway, clock: FakeClock
) -> None:
    gateway.move(TDBU, {P: 0.5, S: 0.0})
    await loaded.async_refresh()
    await _call(hass, SERVICE_SET_COVER_POSITION, TOP, **{ATTR_POSITION: 60})
    gateway.move(TDBU, {S: 0.3})
    await _poll(hass, clock)
    gateway.move(TDBU, {S: 0.5})
    await _poll(hass, clock)
    for _ in range(5):
        await _poll(hass, clock)
    assert state(hass, TOP).state == CoverState.OPENING
    await _poll(hass, clock)
    assert state(hass, TOP).state == CoverState.OPEN
    assert _position(hass, TOP) == 50


async def test_a_command_to_where_the_shade_is_does_not_show_it_moving(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    await _call(hass, SERVICE_SET_COVER_POSITION, BOTTOM_UP_COVER, **{ATTR_POSITION: 40})
    assert state(hass, BOTTOM_UP_COVER).state == CoverState.OPEN
    assert len(_moves(gateway)) == 1


async def test_stop_stops_the_shade_and_it_is_followed_until_still(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway, clock: FakeClock
) -> None:
    await _call(hass, SERVICE_OPEN_COVER, BOTTOM_UP_COVER)
    gateway.move(BOTTOM_UP, {P: 0.5})
    await _poll(hass, clock)
    await _call(hass, SERVICE_STOP_COVER, BOTTOM_UP_COVER)
    assert gateway.requests[-1].path == "/home/shades/stop"
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == CoverState.OPEN)
    assert _position(hass, BOTTOM_UP_COVER) == 50


async def test_a_stop_sent_while_nothing_moves_is_still_sent(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    await _call(hass, SERVICE_STOP_COVER, BOTTOM_UP_COVER)
    assert gateway.requests[-1].path == "/home/shades/stop"


async def test_a_command_the_gateway_reports_an_error_for_is_an_error(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.command_errors[BOTTOM_UP] = 7
    with pytest.raises(HomeAssistantError, match="did not take the command") as raised:
        await _call(hass, SERVICE_OPEN_COVER, BOTTOM_UP_COVER)
    assert raised.value.translation_key == "command_failed"
    with pytest.raises(HomeAssistantError, match="did not take the command"):
        await _call(hass, SERVICE_STOP_COVER, BOTTOM_UP_COVER)
    assert state(hass, BOTTOM_UP_COVER).state == CoverState.OPEN


async def test_a_moving_shade_that_cannot_be_read_still_stops_being_followed(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway, clock: FakeClock
) -> None:
    await _call(hass, SERVICE_OPEN_COVER, BOTTOM_UP_COVER)
    gateway.remove_shade(BOTTOM_UP)
    await _poll(hass, clock)
    assert state(hass, BOTTOM_UP_COVER).state == CoverState.OPENING
    await _poll(hass, clock, 25)
    assert state(hass, BOTTOM_UP_COVER).state == CoverState.OPEN


async def test_set_positions_moves_both_rails_in_one_command(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    await hass.services.async_call(
        DOMAIN, SERVICE_SET_POSITIONS, {ATTR_ENTITY_ID: TOP, "top": 30, "bottom": 40},
        blocking=True,
    )
    assert _moves(gateway) == [(str(TDBU), {"positions": {"primary": 0.4, "secondary": 0.3}})]
    assert state(hass, TOP).state == CoverState.CLOSING
    assert state(hass, BOTTOM).state == CoverState.OPENING


@pytest.mark.parametrize(("data", "sent"), [({"top": 0}, {"secondary": 0.0}),
                                            ({"bottom": 100}, {"primary": 1.0})])
async def test_set_positions_moves_only_the_rails_given(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway,
    data: dict[str, int], sent: dict[str, float],
) -> None:
    await hass.services.async_call(
        DOMAIN, SERVICE_SET_POSITIONS, {ATTR_ENTITY_ID: BOTTOM, **data}, blocking=True)
    assert _moves(gateway) == [(str(TDBU), {"positions": sent})]


async def test_set_positions_needs_a_top_down_bottom_up_shade_and_a_rail(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_POSITIONS, {ATTR_ENTITY_ID: BOTTOM_UP_COVER, "top": 10},
            blocking=True)
    assert raised.value.translation_key == "not_top_down_bottom_up"
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_POSITIONS, {ATTR_ENTITY_ID: TOP}, blocking=True)
    assert raised.value.translation_key == "no_position"
    assert _moves(gateway) == []


async def test_a_shade_moved_by_a_scene_is_followed(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway, clock: FakeClock
) -> None:
    await hass.services.async_call(
        "scene", "turn_on", {ATTR_ENTITY_ID: "scene.simulated_gateway_morning"}, blocking=True)
    assert gateway.requests[-1].path == "/home/scenes/216/activate"
    await until(lambda: state(hass, TOP).state == CoverState.CLOSING)
    gateway.finish(TDBU)
    await until(lambda: state(hass, TOP).state == CoverState.CLOSED)


async def test_a_scene_the_gateway_refuses_is_an_error(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.scenes.clear()
    with pytest.raises(HomeAssistantError, match="did not take the command"):
        await hass.services.async_call(
            "scene", "turn_on", {ATTR_ENTITY_ID: "scene.simulated_gateway_morning"},
            blocking=True)
