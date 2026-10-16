"""Setting up a home, its devices, and keeping it current while the gateway comes and goes."""

from __future__ import annotations

import logging

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from powerview_connect import Connection
from powerview_connect.testing import ManualClock, SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerview_connect import async_remove_config_entry_device, runtime
from custom_components.powerview_connect.const import DOMAIN
from custom_components.powerview_connect.runtime import PowerViewRuntime, timing_from

from .conftest import BOTTOM_UP, SERIAL, TDBU, P, S, state, tick_until, until

BOTTOM_UP_COVER = "cover.living_room_patio_door"
TOP_COVER = "cover.living_room_kitchen_window_top"


async def test_a_gateway_that_does_not_answer_is_tried_again_later(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway
) -> None:
    await gateway.close()
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert config_entry.reason is not None and "does not answer" in config_entry.reason


async def test_the_gateway_and_each_shade_are_devices(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime
) -> None:
    devices = dr.async_get(hass)
    gateway = devices.async_get_device_by_identifier((DOMAIN, SERIAL), config_entry.entry_id)
    assert gateway is not None
    assert (gateway.name, gateway.model, gateway.sw_version, gateway.serial_number) == (
        "Simulated Gateway", "PowerView Gen 3 Gateway Pro", "3.2.59", SERIAL)
    await until(lambda: _hardware(devices, gateway.id) == "3.0.4")
    assert gateway.configuration_url == f"{loaded.hub.base_url}/home"
    shade = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{TDBU}"), config_entry.entry_id
    )
    assert shade is not None
    assert (shade.name, shade.model, shade.sw_version, shade.serial_number) == (
        "Kitchen Window", "Top Down Bottom Up (type 8)", "3.0.433", "0000000000000154")
    assert shade.via_device_id == gateway.id
    assert shade.suggested_area == "Living Room"
    entities = er.async_entries_for_config_entry(er.async_get(hass), config_entry.entry_id)
    assert sorted(entity.entity_id for entity in entities if entity.domain != "button") == [
        "binary_sensor.bedroom_roller_battery", "binary_sensor.simulated_gateway_connection",
        "binary_sensor.simulated_gateway_internet", "cover.bedroom_blind", "cover.bedroom_roller",
        "cover.bedroom_skylight", "cover.living_room_kitchen_window_bottom",
        "cover.living_room_kitchen_window_top", "cover.living_room_patio_door",
        "scene.simulated_gateway_morning", "sensor.bedroom_roller_battery_level",
        "sensor.bedroom_roller_signal_strength", "sensor.bedroom_skylight_signal_strength",
        "sensor.living_room_kitchen_window_signal_strength",
        "sensor.living_room_patio_door_signal_strength", "sensor.simulated_gateway_network",
    ]


async def test_a_shade_of_capabilities_not_known_is_named_by_its_number(
    hass: HomeAssistant, gateway: SimulatedGateway, config_entry: MockConfigEntry
) -> None:
    gateway.add_shade(9, "Odd", room_id=65, capabilities=42)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_9"), config_entry.entry_id
    )
    assert device is not None and device.model == "Capabilities 42 (type 6)"
    assert hass.states.get("cover.living_room_odd") is not None
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_unloading_stops_listening_to_the_gateway(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime,
    gateway: SimulatedGateway,
) -> None:
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await until(lambda: gateway.streams == 0)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_the_device_of_a_shade_the_home_no_longer_has_is_removed(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway
) -> None:
    config_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    stale = devices.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, f"{SERIAL}_999")})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert devices.async_get(stale.id) is None
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_only_a_device_the_home_no_longer_has_can_be_removed(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime
) -> None:
    devices = dr.async_get(hass)
    shade = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{TDBU}"), config_entry.entry_id
    )
    gateway = devices.async_get_device_by_identifier((DOMAIN, SERIAL), config_entry.entry_id)
    gone = devices.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, f"{SERIAL}_999")})
    assert shade is not None and gateway is not None
    assert not await async_remove_config_entry_device(hass, config_entry, shade)
    assert not await async_remove_config_entry_device(hass, config_entry, gateway)
    assert await async_remove_config_entry_device(hass, config_entry, gone)


async def test_a_shade_added_to_the_home_is_added_without_a_reload(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime,
    gateway: SimulatedGateway,
) -> None:
    gateway.add_shade(500, "New Shade", room_id=65)
    await loaded.hub.refresh()
    await until(lambda: hass.states.get("cover.living_room_new_shade") is not None)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_500"), config_entry.entry_id)
    assert device is not None and config_entry.runtime_data is loaded


async def test_a_shade_removed_from_the_home_is_removed_once_two_reads_agree(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime,
    gateway: SimulatedGateway,
) -> None:
    devices = dr.async_get(hass)
    gateway.remove_shade(BOTTOM_UP)
    await loaded.hub.refresh()
    assert devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{BOTTOM_UP}"), config_entry.entry_id) is not None
    await loaded.hub.refresh()
    await until(lambda: hass.states.get(BOTTOM_UP_COVER) is None)
    assert devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{BOTTOM_UP}"), config_entry.entry_id) is None


async def test_a_renamed_shade_keeps_its_device_with_its_new_name(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime,
    gateway: SimulatedGateway,
) -> None:
    gateway.shades[BOTTOM_UP].name = "Back Door"
    await loaded.hub.refresh()
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{BOTTOM_UP}"), config_entry.entry_id)
    assert device is not None and device.name == "Back Door"


async def test_a_scene_removed_from_the_home_is_removed_once_two_reads_agree(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    gateway.scenes.clear()
    await loaded.hub.refresh()
    assert hass.states.get("scene.simulated_gateway_morning") is not None
    await loaded.hub.refresh()
    await until(lambda: hass.states.get("scene.simulated_gateway_morning") is None)


async def test_a_refresh_takes_positions_changed_without_an_event(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway, clock: ManualClock
) -> None:
    gateway.move(BOTTOM_UP, {P: 0.9})
    await clock.advance(600)
    await until(lambda: _position(hass, BOTTOM_UP_COVER) == 90)


def test_a_hub_keeps_the_time_of_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()
    assert runtime.new_clock() is None


def test_the_poll_and_refresh_intervals_are_options() -> None:
    timing = timing_from({"refresh_minutes": 1, "motion_poll_interval": 2.0})
    assert (timing.refresh_interval, timing.poll_interval) == (60.0, 2.0)
    default = timing_from({})
    assert (default.refresh_interval, default.poll_interval) == (600.0, 1.0)
    assert timing_from({"refresh_minutes": "x", "motion_poll_interval": None}) == default


async def test_entities_are_unavailable_while_the_gateway_does_not_answer(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway, clock: ManualClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    await gateway.close()
    await tick_until(clock, lambda: state(hass, BOTTOM_UP_COVER).state == STATE_UNAVAILABLE)
    assert state(hass, "scene.simulated_gateway_morning").state == STATE_UNAVAILABLE
    gateway.move(BOTTOM_UP, {P: 0.7})
    await gateway.start()
    await tick_until(clock, lambda: loaded.hub.connection is Connection.CONNECTED
                     and _position(hass, BOTTOM_UP_COVER) == 70)
    assert state(hass, BOTTOM_UP_COVER).state == "open"
    warnings = [r for r in caplog.records if "does not answer" in r.getMessage()]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING


async def test_the_event_stream_is_reopened_and_what_was_missed_is_read(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway, clock: ManualClock
) -> None:
    gateway.drop_streams()
    gateway.move(TDBU, {S: 0.3})
    await tick_until(clock, lambda: _position(hass, TOP_COVER) == 30)
    assert state(hass, TOP_COVER).state != STATE_UNAVAILABLE


async def test_a_shade_the_gateway_reports_offline_is_unavailable_until_it_is_back(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    gateway.set_online(BOTTOM_UP, False)
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == STATE_UNAVAILABLE)
    assert state(hass, TOP_COVER).state != STATE_UNAVAILABLE
    gateway.set_online(BOTTOM_UP, True)
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == "open")


async def test_events_of_other_kinds_and_other_shades_change_nothing(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    gateway.emit("battery-alert", TDBU, batteryLevel=1)
    gateway.emit("motion-started", 999, targetPositions={"primary": 1})
    gateway.set_online(BOTTOM_UP, False)
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == STATE_UNAVAILABLE)
    assert not loaded.hub.shade(TDBU).moving
    assert loaded.hub.shade(TDBU).positions[S] == 0.71


def _hardware(devices: dr.DeviceRegistry, device_id: str) -> str | None:
    device = devices.async_get(device_id)
    return device.hw_version if isinstance(device, dr.DeviceEntry) else None


def _position(hass: HomeAssistant, entity_id: str) -> int | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    position = state.attributes.get("current_position")
    return position if isinstance(position, int) else None


async def test_an_entity_the_integration_no_longer_makes_is_removed(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway
) -> None:
    """Such as a button a former version made for each shade."""
    config_entry.add_to_hass(hass)
    entities = er.async_get(hass)
    gone = entities.async_get_or_create(
        "button", DOMAIN, f"{SERIAL}_{TDBU}_favorite", config_entry=config_entry)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert entities.async_get(gone.entity_id) is None
    assert entities.async_get("cover.living_room_kitchen_window_top") is not None
    await hass.config_entries.async_unload(config_entry.entry_id)
