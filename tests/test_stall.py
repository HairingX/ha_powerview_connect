"""Curtains that stop short of fully open: raised in steps when the option is on, and an event for
automations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from homeassistant.const import CONF_HOST
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from powerview_connect import Connection, PowerViewHub
from powerview_connect.testing import ManualClock, SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.powerview_connect.const import DOMAIN, EVENT_SHADE_STALLED
from custom_components.powerview_connect.runtime import PowerViewRuntime

from .conftest import BOTTOM_UP, SERIAL, TDBU, TITLE, P, S, tick, until

PATIO = "cover.living_room_patio_door"
BOTTOM = "cover.living_room_kitchen_window_bottom"
RAISING: dict[str, object] = {"raise_stalled": True, "stall_pause": 10.0, "stall_min_position": 80}


async def _set_up(hass: HomeAssistant, gateway: SimulatedGateway,
                  options: dict[str, object]) -> AsyncIterator[PowerViewRuntime]:
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, unique_id=SERIAL,
                            data={CONF_HOST: gateway.host}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime: PowerViewRuntime = entry.runtime_data
    await until(lambda: runtime.hub.connection is Connection.CONNECTED)
    yield runtime
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.fixture
async def raising(hass: HomeAssistant, gateway: SimulatedGateway) -> AsyncIterator[PowerViewRuntime]:
    """The entry, set up with curtains that stop short raised."""
    async for runtime in _set_up(hass, gateway, RAISING):
        yield runtime


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


async def test_a_curtain_that_stops_short_is_raised_and_an_event_says_so(
    hass: HomeAssistant, gateway: SimulatedGateway, raising: PowerViewRuntime, clock: ManualClock
) -> None:
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, raising, BOTTOM_UP, 0.9)
    await until(lambda: len(events) == 1)
    assert events[0].data == {"entity_id": PATIO, "outcome": "recovering", "position": 90}
    await _steps_succeed(gateway, raising, clock, BOTTOM_UP, events)
    assert events[1].data == {"entity_id": PATIO, "outcome": "recovered", "position": 100}


async def test_the_event_names_the_bottom_rail_of_a_top_down_bottom_up_shade(
    hass: HomeAssistant, gateway: SimulatedGateway, raising: PowerViewRuntime
) -> None:
    gateway.shades[TDBU].positions[S] = 0.0
    await raising.hub.refresh()
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, raising, TDBU, 0.85)
    await until(lambda: len(events) == 1)
    assert events[0].data == {"entity_id": BOTTOM, "outcome": "recovering", "position": 85}


async def test_a_curtain_that_stops_short_is_left_there_when_the_option_is_off(
    hass: HomeAssistant, gateway: SimulatedGateway, loaded: PowerViewRuntime
) -> None:
    events = async_capture_events(hass, EVENT_SHADE_STALLED)
    await _opened_by_the_app(hass, gateway, loaded, BOTTOM_UP, 0.9)
    await until(lambda: loaded.hub.shade(BOTTOM_UP).positions[P] == 0.9)
    await asyncio.sleep(0.1)
    assert events == []
    assert len([request for request in gateway.requests if request.method == "PUT"]) == 1
