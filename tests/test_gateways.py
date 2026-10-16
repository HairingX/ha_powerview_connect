"""Each gateway of the home as a device: whether it answers, reaches the internet, and its network."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.powerview_connect import async_remove_config_entry_device
from custom_components.powerview_connect.const import DOMAIN
from custom_components.powerview_connect.diagnostics import async_get_config_entry_diagnostics
from custom_components.powerview_connect.hub import PowerViewHub

from .conftest import ON_BATTERY, SERIAL, TDBU, state, until

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


async def _set_up(hass: HomeAssistant, config_entry: MockConfigEntry) -> PowerViewHub:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry.runtime_data


async def _minutes_later(hass: HomeAssistant, minutes: int, entity_id: str, expected: str) -> None:
    """Let `minutes` pass since the setup, until `entity_id` is `expected`."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes, seconds=1))
    await hass.async_block_till_done()
    await until(lambda: state(hass, entity_id).state == expected)


async def test_a_gateway_that_answers_is_connected_reaches_the_internet_and_is_wired(
    hass: HomeAssistant, loaded: PowerViewHub
) -> None:
    assert state(hass, CONNECTION).state == STATE_ON
    assert state(hass, INTERNET).state == STATE_ON
    assert state(hass, NETWORK).state == "wired"


async def test_a_gateway_without_internet_or_on_wifi_says_so_within_a_minute(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.internet_state, gateway.interface = "Disconnected", "wlan0"
    await _minutes_later(hass, 1, INTERNET, STATE_OFF)
    assert state(hass, NETWORK).state == "wifi"
    gateway.interface = "usb0"
    await _minutes_later(hass, 2, NETWORK, STATE_UNKNOWN)


async def test_an_auxiliary_gateway_is_a_device_its_shades_are_connected_through(
    hass: HomeAssistant, config_entry: MockConfigEntry, auxiliary: SimulatedGateway
) -> None:
    hub = await _set_up(hass, config_entry)
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
    await hass.config_entries.async_unload(hub.entry.entry_id)


async def test_a_gateway_that_stops_answering_is_disconnected_until_it_answers_again(
    hass: HomeAssistant, config_entry: MockConfigEntry, auxiliary: SimulatedGateway
) -> None:
    hub = await _set_up(hass, config_entry)
    await auxiliary.close()
    await _minutes_later(hass, 1, AUX_CONNECTION, STATE_OFF)
    assert state(hass, AUX_INTERNET).state == STATE_UNAVAILABLE
    assert state(hass, AUX_NETWORK).state == STATE_UNAVAILABLE
    assert state(hass, CONNECTION).state == STATE_ON
    await auxiliary.start()
    await _minutes_later(hass, 2, AUX_CONNECTION, STATE_ON)
    assert state(hass, AUX_INTERNET).state == STATE_ON
    await hass.config_entries.async_unload(hub.entry.entry_id)


async def test_an_auxiliary_gateway_that_does_not_answer_at_setup_is_set_up_disconnected(
    hass: HomeAssistant, config_entry: MockConfigEntry, auxiliary: SimulatedGateway
) -> None:
    await auxiliary.close()
    hub = await _set_up(hass, config_entry)
    assert state(hass, AUX_CONNECTION).state == STATE_OFF
    assert state(hass, CONNECTION).state == STATE_ON
    await hass.config_entries.async_unload(hub.entry.entry_id)


async def test_a_gateway_listed_without_an_address_is_a_device_without_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway
) -> None:
    gateway.add_gateway(AUX, "Bedroom Gateway", ip="")
    hub = await _set_up(hass, config_entry)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_gateway_{AUX}"), config_entry.entry_id)
    assert device is not None and device.hw_version is None
    assert hass.states.get(AUX_CONNECTION) is None
    await hass.config_entries.async_unload(hub.entry.entry_id)


async def test_an_error_that_is_not_the_gateways_is_not_taken_for_one_not_answering(
    hass: HomeAssistant, loaded: PowerViewHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken() -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(loaded.gateway_clients[SERIAL], "get_gateway", broken)
    with pytest.raises(RuntimeError, match="a bug"):
        await loaded.async_refresh_gateways()
    assert state(hass, CONNECTION).state == STATE_ON


async def test_a_home_that_lists_no_gateway_has_a_gateway_device_without_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway
) -> None:
    gateway.gateways.clear()
    hub = await _set_up(hass, config_entry)
    devices = dr.async_get(hass)
    primary = devices.async_get_device_by_identifier((DOMAIN, SERIAL), config_entry.entry_id)
    window = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{TDBU}"), config_entry.entry_id)
    assert primary is not None and primary.name == "PowerView Gateway"
    assert window is not None and window.via_device_id == primary.id
    assert hass.states.get(CONNECTION) is None
    await hass.config_entries.async_unload(hub.entry.entry_id)


async def test_diagnostics_say_which_gateway_does_not_answer_and_which_is_not_asked(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway,
    auxiliary: SimulatedGateway,
) -> None:
    gateway.add_gateway("AUX-0003", "Hall Gateway", ip="")
    await auxiliary.close()
    hub = await _set_up(hass, config_entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, hub.entry)
    assert [found["status"] for found in diagnostics["gateways"][1:]] == [
        "not answering", "not asked"]
    assert diagnostics["gateways"][1]["shades"] == [ON_BATTERY]
    assert AUX not in json.dumps(diagnostics) and auxiliary.host not in json.dumps(diagnostics)
    await hass.config_entries.async_unload(hub.entry.entry_id)
