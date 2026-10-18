"""Retrying a stalled opening: a switch and a delay on each pleated shade, restored after a
restart, and an event for automations."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from powerview_connect import (
    Connection,
    CoverRole,
    PowerViewHub,
    StalledOpenRetry,
)
from powerview_connect.testing import ManualClock, SimulatedGateway
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    mock_restore_cache_with_extra_data,
)

from custom_components.powerview_connect.const import EVENT_SHADE_STALLED
from custom_components.powerview_connect.runtime import PowerViewRuntime

from .conftest import BOTTOM_UP, TDBU, P, S, state, until

PATIO = "cover.living_room_patio_door"
BOTTOM = "cover.living_room_kitchen_window_bottom"
PATIO_SWITCH = "switch.living_room_patio_door_retry_stalled_opening"
PATIO_DELAY = "number.living_room_patio_door_retry_stalled_opening_delay"
WINDOW_SWITCH = "switch.living_room_kitchen_window_retry_stalled_opening"


async def _switch(hass: HomeAssistant, entity_id: str, on: bool) -> None:
    await hass.services.async_call("switch", SERVICE_TURN_ON if on else SERVICE_TURN_OFF,
                                   {ATTR_ENTITY_ID: entity_id}, blocking=True)


async def _number(hass: HomeAssistant, entity_id: str, value: float) -> None:
    await hass.services.async_call("number", "set_value",
                                   {ATTR_ENTITY_ID: entity_id, "value": value}, blocking=True)


async def _set_up(hass: HomeAssistant, entry: MockConfigEntry) -> PowerViewRuntime:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime: PowerViewRuntime = entry.runtime_data
    await until(lambda: runtime.hub.connection is Connection.CONNECTED)
    return runtime


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
    """Let the retry's waits pass, ending each of its steps at its target, until it has ended."""
    while len(events) < 2:
        if gateway.shades[shade_id].target is not None:
            gateway.finish(shade_id)
            await until(lambda: not runtime.hub.shade(shade_id).moving)
        await clock.advance(10.0)
        await asyncio.sleep(0.02)


async def test_each_pleated_shade_has_the_retry_off_with_its_delay(
    hass: HomeAssistant, loaded: PowerViewRuntime
) -> None:
    switches = {found.entity_id: found.state for found in hass.states.async_all("switch")}
    assert switches == {
        PATIO_SWITCH: STATE_OFF, WINDOW_SWITCH: STATE_OFF,
        "switch.bedroom_skylight_retry_stalled_opening": STATE_OFF,
        "switch.bedroom_roller_retry_stalled_opening": STATE_OFF,
    }
    assert state(hass, PATIO_DELAY).state == "300.0"
    assert loaded.hub.stalled_open_retry(BOTTOM_UP, CoverRole.SHADE) is None


async def test_a_shade_with_the_retry_on_whose_opening_stalls_is_opened_and_an_event_says_so(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime, clock: ManualClock
) -> None:
    await _switch(hass, PATIO_SWITCH, True)
    assert state(hass, PATIO_SWITCH).state == STATE_ON
    assert loaded.hub.stalled_open_retry(BOTTOM_UP, CoverRole.SHADE) == StalledOpenRetry(delay=300.0)
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, BOTTOM_UP, 0.9)
    await until(lambda: len(events) == 1)
    assert events[0].data == {"entity_id": PATIO, "outcome": "started", "position": 90}
    await _steps_succeed(gateway, loaded, clock, BOTTOM_UP, events)
    assert events[1].data == {"entity_id": PATIO, "outcome": "opened", "position": 100}


async def test_the_delay_of_a_shade_goes_to_the_hub(
    hass: HomeAssistant, loaded: PowerViewRuntime
) -> None:
    await _number(hass, PATIO_DELAY, 45)
    assert loaded.hub.stalled_open_retry(BOTTOM_UP, CoverRole.SHADE) is None
    await _switch(hass, PATIO_SWITCH, True)
    assert loaded.hub.stalled_open_retry(BOTTOM_UP, CoverRole.SHADE) == StalledOpenRetry(delay=45.0)
    await _number(hass, PATIO_DELAY, 120)
    assert loaded.hub.stalled_open_retry(BOTTOM_UP, CoverRole.SHADE) == StalledOpenRetry(delay=120.0)
    assert state(hass, PATIO_DELAY).state == "120.0"


async def test_the_event_names_the_bottom_rail_of_a_top_down_bottom_up_shade(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime
) -> None:
    gateway.shades[TDBU].positions[S] = 0.0
    await loaded.hub.refresh()
    await _switch(hass, WINDOW_SWITCH, True)
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, TDBU, 0.85)
    await until(lambda: len(events) == 1)
    assert events[0].data == {"entity_id": BOTTOM, "outcome": "started", "position": 85}


async def test_switching_the_retry_off_during_one_ends_it(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime
) -> None:
    await _switch(hass, PATIO_SWITCH, True)
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, BOTTOM_UP, 0.9)
    await until(lambda: len(events) == 1)
    await _switch(hass, PATIO_SWITCH, False)
    await until(lambda: len(events) == 2)
    assert events[1].data["outcome"] == "interrupted"
    assert loaded.hub.stalled_open_retry(BOTTOM_UP, CoverRole.SHADE) is None


async def test_a_stall_of_a_cover_without_an_entity_fires_no_event(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime, clock: ManualClock
) -> None:
    await _switch(hass, PATIO_SWITCH, True)
    er.async_get(hass).async_remove(PATIO)
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, BOTTOM_UP, 0.9)
    await until(lambda: not loaded.hub.shade(BOTTOM_UP).moving)
    await clock.advance(331.0)
    await until(lambda: len([found for found in gateway.requests if found.method == "PUT"]) == 2)
    await asyncio.sleep(0.05)
    assert events == []


async def test_settings_for_a_shade_the_hub_no_longer_has_reach_nothing(
    loaded: PowerViewRuntime,
) -> None:
    loaded.retry(9999, CoverRole.SHADE).on = True
    loaded.apply_retry(9999, CoverRole.SHADE)
    assert 9999 not in loaded.hub.shades


async def test_a_shade_with_the_retry_off_whose_opening_stalls_is_left_there(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime
) -> None:
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, BOTTOM_UP, 0.9)
    await until(lambda: loaded.hub.shade(BOTTOM_UP).positions[P] == 0.9)
    await asyncio.sleep(0.1)
    assert events == []
    assert len([request for request in gateway.requests if request.method == "PUT"]) == 1


async def test_the_switch_and_settings_are_restored_after_a_restart(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway,
) -> None:
    # One cache holds both: a second call would replace the first.
    mock_restore_cache_with_extra_data(hass, [
        (State(PATIO_SWITCH, STATE_ON), {}),
        (State(PATIO_DELAY, "120"), {"native_value": 120.0, "native_unit_of_measurement": "s",
                                     "native_min_value": 0, "native_max_value": 600,
                                     "native_step": 1}),
    ])
    runtime = await _set_up(hass, config_entry)
    assert runtime.hub.stalled_open_retry(BOTTOM_UP, CoverRole.SHADE) == StalledOpenRetry(delay=120.0)
    assert runtime.hub.stalled_open_retry(TDBU, CoverRole.BOTTOM) is None
    assert state(hass, PATIO_SWITCH).state == STATE_ON
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_disabled_switch_retries_nothing(
    hass: HomeAssistant, loaded: PowerViewRuntime
) -> None:
    await _switch(hass, PATIO_SWITCH, True)
    er.async_get(hass).async_update_entity(PATIO_SWITCH, disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()
    assert loaded.hub.stalled_open_retry(BOTTOM_UP, CoverRole.SHADE) is None
