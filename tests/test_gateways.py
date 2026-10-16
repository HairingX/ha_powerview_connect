"""Each gateway of the home as a device: whether it answers, reaches the internet, and its network."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from powerview_connect.testing import ManualClock, SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerview_connect import async_remove_config_entry_device
from custom_components.powerview_connect.const import DOMAIN
from custom_components.powerview_connect.diagnostics import async_get_config_entry_diagnostics
from custom_components.powerview_connect.runtime import PowerViewRuntime

from .conftest import ON_BATTERY, SERIAL, TDBU, state, tick, until

AUX = "AUX-0002"
CONNECTION = "binary_sensor.simulated_gateway_connection"
INTERNET = "binary_sensor.simulated_gateway_internet"
NETWORK = "sensor.simulated_gateway_network"
AUX_CONNECTION = "binary_sensor.bedroom_gateway_connection"
AUX_INTERNET = "binary_sensor.bedroom_gateway_internet"
AUX_NETWORK = "sensor.bedroom_gateway_network"


@pytest.fixture
async def auxiliary(gateway: SimulatedGateway) -> AsyncIterator[SimulatedGateway]:
    """An auxiliary gateway, listed in the primary gateway's home, serving the battery shade."""
    async with SimulatedGateway(serial=AUX, name="Bedroom Gateway", primary=False) as simulated:
        gateway.add_gateway(AUX, "Bedroom Gateway", ip=simulated.host)
        gateway.shades[ON_BATTERY].gateway = AUX
        yield simulated


async def _set_up(hass: HomeAssistant, config_entry: MockConfigEntry) -> PowerViewRuntime:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    runtime: PowerViewRuntime = config_entry.runtime_data
    # The gateways are first asked once the hub runs.
    await until(lambda: all(state.reachable is not None
                            for state in runtime.hub.gateways.values() if state.askable))
    return runtime


async def _a_minute_later(clock: ManualClock, hass: HomeAssistant, entity_id: str,
                          expected: str) -> None:
    """Let a minute pass, until `entity_id` is `expected`."""
    await clock.advance(60)
    await tick(clock)
    await until(lambda: state(hass, entity_id).state == expected)


async def test_a_gateway_that_answers_is_connected_reaches_the_internet_and_is_wired(
    hass: HomeAssistant, loaded: PowerViewRuntime
) -> None:
    assert state(hass, CONNECTION).state == STATE_ON
    assert state(hass, INTERNET).state == STATE_ON
    assert state(hass, NETWORK).state == "wired"


async def test_a_gateway_without_internet_or_on_wifi_says_so_within_a_minute(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway, clock: ManualClock
) -> None:
    gateway.internet_state, gateway.interface = "Disconnected", "wlan0"
    await _a_minute_later(clock, hass, INTERNET, STATE_OFF)
    assert state(hass, NETWORK).state == "wifi"
    gateway.interface = "usb0"
    await _a_minute_later(clock, hass, NETWORK, STATE_UNKNOWN)


async def test_an_auxiliary_gateway_is_a_device_its_shades_are_connected_through(
    hass: HomeAssistant, config_entry: MockConfigEntry, auxiliary: SimulatedGateway
) -> None:
    await _set_up(hass, config_entry)
    devices = dr.async_get(hass)
    primary = devices.async_get_device_by_identifier((DOMAIN, SERIAL), config_entry.entry_id)
    device = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_gateway_{AUX}"), config_entry.entry_id)
    assert primary is not None and device is not None
    assert (device.name, device.serial_number, device.hw_version, device.via_device_id) == (
        "Bedroom Gateway", AUX, "3.0.4", primary.id)
    roller = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{ON_BATTERY}"), config_entry.entry_id)
    window = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{TDBU}"), config_entry.entry_id)
    assert roller is not None and roller.via_device_id == device.id
    assert window is not None and window.via_device_id == primary.id
    assert (state(hass, AUX_CONNECTION).state, state(hass, AUX_INTERNET).state,
            state(hass, AUX_NETWORK).state) == (STATE_ON, STATE_ON, "wired")
    assert not await async_remove_config_entry_device(hass, config_entry, device)
    assert auxiliary.requests[-1].path == "/gateway"
    assert all(request.method == "GET" for request in auxiliary.requests)
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_gateway_that_stops_answering_is_disconnected_until_it_answers_again(
    hass: HomeAssistant, config_entry: MockConfigEntry, auxiliary: SimulatedGateway, clock: ManualClock
) -> None:
    await _set_up(hass, config_entry)
    await auxiliary.close()
    await _a_minute_later(clock, hass, AUX_CONNECTION, STATE_OFF)
    assert state(hass, AUX_INTERNET).state == STATE_UNAVAILABLE
    assert state(hass, AUX_NETWORK).state == STATE_UNAVAILABLE
    assert state(hass, CONNECTION).state == STATE_ON
    await auxiliary.start()
    await _a_minute_later(clock, hass, AUX_CONNECTION, STATE_ON)
    assert state(hass, AUX_INTERNET).state == STATE_ON
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_an_auxiliary_gateway_that_does_not_answer_at_setup_is_set_up_disconnected(
    hass: HomeAssistant, config_entry: MockConfigEntry, auxiliary: SimulatedGateway
) -> None:
    await auxiliary.close()
    await _set_up(hass, config_entry)
    assert state(hass, AUX_CONNECTION).state == STATE_OFF
    assert state(hass, CONNECTION).state == STATE_ON
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_gateway_listed_without_an_address_is_a_device_without_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway
) -> None:
    gateway.add_gateway(AUX, "Bedroom Gateway", ip="")
    await _set_up(hass, config_entry)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_gateway_{AUX}"), config_entry.entry_id)
    assert device is not None and device.hw_version is None
    assert hass.states.get(AUX_CONNECTION) is None
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_home_that_lists_no_gateway_has_a_gateway_device_without_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway
) -> None:
    gateway.gateways.clear()
    await _set_up(hass, config_entry)
    devices = dr.async_get(hass)
    primary = devices.async_get_device_by_identifier((DOMAIN, SERIAL), config_entry.entry_id)
    window = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{TDBU}"), config_entry.entry_id)
    assert primary is not None and primary.name == "PowerView Gateway"
    assert window is not None and window.via_device_id == primary.id
    assert hass.states.get(CONNECTION) is None
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_diagnostics_say_which_gateway_does_not_answer_and_which_is_not_asked(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway,
    auxiliary: SimulatedGateway,
) -> None:
    gateway.add_gateway("AUX-0003", "Hall Gateway", ip="")
    await auxiliary.close()
    await _set_up(hass, config_entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    gateways = diagnostics["hub"]["gateways"]
    assert [(found["askable"], found["reachable"]) for found in gateways[1:]] == [
        (True, False), (False, None)]
    assert gateways[1]["shades"] == [ON_BATTERY]
    assert AUX not in json.dumps(diagnostics) and auxiliary.host not in json.dumps(diagnostics)
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_an_auxiliary_gateway_added_to_the_home_is_added_without_a_reload(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime,
    gateway: SimulatedGateway, clock: ManualClock,
) -> None:
    async with SimulatedGateway(serial=AUX, name="Bedroom Gateway", primary=False) as added:
        gateway.add_gateway(AUX, "Bedroom Gateway", ip=added.host)
        await loaded.hub.refresh()
        devices = dr.async_get(hass)
        device = devices.async_get_device_by_identifier(
            (DOMAIN, f"{SERIAL}_gateway_{AUX}"), config_entry.entry_id)
        assert device is not None and device.via_device_id == loaded.primary_device_id
        await _a_minute_later(clock, hass, AUX_CONNECTION, STATE_ON)
        await until(lambda: _hardware(devices, device.id) == "3.0.4")


def _hardware(devices: dr.DeviceRegistry, device_id: str) -> str | None:
    found = devices.async_get(device_id)
    return found.hw_version if isinstance(found, dr.DeviceEntry) else None
