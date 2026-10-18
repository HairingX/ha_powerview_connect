"""Curtains that stop short of fully open: a switch on each that raises it in steps, kept across
restarts, and an event for automations."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from powerview_connect import Connection, PowerViewHub
from powerview_connect.testing import ManualClock, SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.powerview_connect.const import EVENT_SHADE_STALLED
from custom_components.powerview_connect.runtime import PowerViewRuntime

from .conftest import BOTTOM_UP, TDBU, P, S, state, tick, until

SWITCH_DOMAIN = "switch"
PATIO = "cover.living_room_patio_door"
BOTTOM = "cover.living_room_kitchen_window_bottom"
PATIO_SWITCH = "switch.living_room_patio_door_raise_if_it_stops_short"
WINDOW_SWITCH = "switch.living_room_kitchen_window_raise_if_it_stops_short"


async def _switch(hass: HomeAssistant, entity_id: str, on: bool) -> None:
    await hass.services.async_call(SWITCH_DOMAIN, SERVICE_TURN_ON if on else SERVICE_TURN_OFF,
                                   {ATTR_ENTITY_ID: entity_id}, blocking=True)


async def _opened_by_the_app(hass: HomeAssistant, gateway: SimulatedGateway,
                             runtime: PowerViewRuntime, shade_id: int, at: float) -> None:
    """The PowerView app opens the shade fully, and it stops at `at`."""
    app = PowerViewHub(async_get_clientsession(hass), gateway.host)
    await app.load()
    await app.move(shade_id, {P: 1.0})
    await until(lambda: runtime.hub.shade(shade_id).moving)
    gateway.finish(shade_id, at={P: at})


async def _steps_succeed(gateway: SimulatedGateway, runtime: PowerViewRuntime, clock: ManualClock,
                         shade_id: int, events: Sequence[Event[dict[str, Any]]]) -> None:
    while len(events) < 2:
        await until(lambda: gateway.shades[shade_id].target is not None or len(events) >= 2)
        if gateway.shades[shade_id].target is not None:
            gateway.finish(shade_id)
            await until(lambda: not runtime.hub.shade(shade_id).moving)
            await asyncio.sleep(0.05)
            await tick(clock, 10.0)


async def test_each_cover_that_can_be_raised_has_a_switch_that_is_off(
    hass: HomeAssistant, loaded: PowerViewRuntime
) -> None:
    switches = {found.entity_id: found.state for found in hass.states.async_all(SWITCH_DOMAIN)}
    assert switches == {
        PATIO_SWITCH: STATE_OFF, WINDOW_SWITCH: STATE_OFF,
        "switch.bedroom_skylight_raise_if_it_stops_short": STATE_OFF,
        "switch.bedroom_roller_raise_if_it_stops_short": STATE_OFF,
    }


async def test_a_curtain_switched_on_that_stops_short_is_raised_and_an_event_says_so(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime, clock: ManualClock
) -> None:
    await _switch(hass, PATIO_SWITCH, True)
    assert state(hass, PATIO_SWITCH).state == STATE_ON
    assert loaded.hub.stall_recovery_enabled(BOTTOM_UP)
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, BOTTOM_UP, 0.9)
    await until(lambda: len(events) == 1)
    assert events[0].data == {"entity_id": PATIO, "outcome": "recovering", "position": 90}
    await _steps_succeed(gateway, loaded, clock, BOTTOM_UP, events)
    assert events[1].data == {"entity_id": PATIO, "outcome": "recovered", "position": 100}


async def test_the_event_names_the_bottom_rail_of_a_top_down_bottom_up_shade(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime
) -> None:
    gateway.shades[TDBU].positions[S] = 0.0
    await loaded.hub.refresh()
    await _switch(hass, WINDOW_SWITCH, True)
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, TDBU, 0.85)
    await until(lambda: len(events) == 1)
    assert events[0].data == {"entity_id": BOTTOM, "outcome": "recovering", "position": 85}


async def test_switching_off_during_a_raise_ends_it(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime
) -> None:
    await _switch(hass, PATIO_SWITCH, True)
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, BOTTOM_UP, 0.9)
    await until(lambda: len(events) == 1)
    await _switch(hass, PATIO_SWITCH, False)
    await until(lambda: len(events) == 2)
    assert events[1].data["outcome"] == "interrupted"
    assert not loaded.hub.stall_recovery_enabled(BOTTOM_UP)


async def test_a_curtain_not_switched_on_that_stops_short_is_left_there(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime
) -> None:
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, BOTTOM_UP, 0.9)
    await until(lambda: loaded.hub.shade(BOTTOM_UP).positions[P] == 0.9)
    await asyncio.sleep(0.1)
    assert events == []
    assert len([request for request in gateway.requests if request.method == "PUT"]) == 1


async def test_a_switch_turned_on_is_on_again_after_a_restart_and_forgotten_with_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway,
    hass_storage: dict[str, Any],
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _switch(hass, PATIO_SWITCH, True)
    await _switch(hass, WINDOW_SWITCH, True)
    await _switch(hass, WINDOW_SWITCH, False)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    runtime: PowerViewRuntime = config_entry.runtime_data
    await until(lambda: runtime.hub.connection is Connection.CONNECTED)
    assert runtime.hub.stall_recovery_enabled(BOTTOM_UP)
    assert not runtime.hub.stall_recovery_enabled(TDBU)
    assert state(hass, PATIO_SWITCH).state == STATE_ON
    key = f"powerview_connect.{config_entry.entry_id}.raised"
    assert hass_storage[key]["data"] == [BOTTOM_UP]
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    assert key not in hass_storage


async def test_a_shade_kept_as_raised_that_the_home_no_longer_has_is_left_out(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway,
    hass_storage: dict[str, Any],
) -> None:
    hass_storage[f"powerview_connect.{config_entry.entry_id}.raised"] = {
        "version": 1, "minor_version": 1, "key": "raised", "data": [BOTTOM_UP, 999]}
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    runtime: PowerViewRuntime = config_entry.runtime_data
    assert runtime.hub.stall_recovery_enabled(BOTTOM_UP)
    await hass.config_entries.async_unload(config_entry.entry_id)
