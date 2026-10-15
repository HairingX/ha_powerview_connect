"""Setting up a home, its devices, and keeping it current while the gateway comes and goes."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from powerview_connect import EventKind
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.powerview_connect import async_remove_config_entry_device
from custom_components.powerview_connect.const import DOMAIN
from custom_components.powerview_connect.hub import PowerViewHub

from .conftest import BOTTOM_UP, SERIAL, TDBU, P, S, state, until

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
    hass: HomeAssistant, loaded: PowerViewHub
) -> None:
    devices = dr.async_get(hass)
    gateway = devices.async_get_device_by_identifier((DOMAIN, SERIAL), loaded.entry.entry_id)
    assert gateway is not None
    assert (gateway.name, gateway.model, gateway.sw_version, gateway.serial_number) == (
        "Simulated Gateway", "PowerView Gen 3 Gateway Pro", "3.2.59", SERIAL)
    assert gateway.configuration_url == f"http://{loaded.client.host}/home"
    shade = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{TDBU}"), loaded.entry.entry_id
    )
    assert shade is not None
    assert (shade.name, shade.model, shade.sw_version, shade.serial_number) == (
        "Kitchen Window", "Top Down Bottom Up (type 8)", "3.0.433", "0000000000000154")
    assert shade.via_device_id == gateway.id
    assert shade.suggested_area == "Living Room"
    entities = er.async_entries_for_config_entry(er.async_get(hass), loaded.entry.entry_id)
    assert sorted(entity.entity_id for entity in entities if entity.domain != "button") == [
        "binary_sensor.bedroom_roller_battery", "cover.bedroom_blind", "cover.bedroom_roller",
        "cover.bedroom_skylight", "cover.living_room_kitchen_window_bottom",
        "cover.living_room_kitchen_window_top", "cover.living_room_patio_door",
        "scene.simulated_gateway_morning", "sensor.bedroom_roller_battery_level",
        "sensor.bedroom_roller_signal_strength", "sensor.bedroom_skylight_signal_strength",
        "sensor.living_room_kitchen_window_signal_strength",
        "sensor.living_room_patio_door_signal_strength",
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
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewHub,
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
    hass: HomeAssistant, loaded: PowerViewHub
) -> None:
    devices = dr.async_get(hass)
    shade = devices.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL}_{TDBU}"), loaded.entry.entry_id
    )
    gateway = devices.async_get_device_by_identifier((DOMAIN, SERIAL), loaded.entry.entry_id)
    gone = devices.async_get_or_create(
        config_entry_id=loaded.entry.entry_id, identifiers={(DOMAIN, f"{SERIAL}_999")})
    assert shade is not None and gateway is not None
    assert not await async_remove_config_entry_device(hass, loaded.entry, shade)
    assert not await async_remove_config_entry_device(hass, loaded.entry, gateway)
    assert await async_remove_config_entry_device(hass, loaded.entry, gone)


async def test_a_shade_added_to_the_home_is_added_at_the_next_refresh(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.add_shade(500, "New Shade", room_id=65)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=10))
    await hass.async_block_till_done()
    await until(lambda: hass.states.get("cover.living_room_new_shade") is not None)


async def test_a_scene_removed_from_the_home_is_removed_at_the_next_refresh(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.scenes.clear()
    await loaded.async_refresh()
    await hass.async_block_till_done()
    await until(lambda: loaded.entry.state is ConfigEntryState.LOADED
                and not loaded.entry.runtime_data.home.scenes)


async def test_a_refresh_takes_positions_changed_without_an_event(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.move(BOTTOM_UP, {P: 0.9})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=10))
    await hass.async_block_till_done()
    await until(lambda: _position(hass, BOTTOM_UP_COVER) == 90)


async def test_the_refresh_interval_is_an_option(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={"host": gateway.host},
                            options={"refresh_minutes": 1, "motion_poll_interval": 2.0})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await gateway.wait_for_stream()
    gateway.move(BOTTOM_UP, {P: 0.1})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=1))
    await hass.async_block_till_done()
    await until(lambda: _position(hass, BOTTOM_UP_COVER) == 10)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_entities_are_unavailable_while_the_gateway_does_not_answer(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    await gateway.close()
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == STATE_UNAVAILABLE)
    assert state(hass, "scene.simulated_gateway_morning").state == STATE_UNAVAILABLE
    await loaded.async_refresh()
    gateway.move(BOTTOM_UP, {P: 0.7})
    await gateway.start()
    await until(lambda: loaded.stream_connected and _position(hass, BOTTOM_UP_COVER) == 70)
    assert state(hass, BOTTOM_UP_COVER).state == "open"
    warnings = [r for r in caplog.records if "does not answer" in r.getMessage()]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert any("answers again" in r.getMessage() for r in caplog.records)


async def test_the_event_stream_is_reopened_and_what_was_missed_is_read(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.drop_streams()
    gateway.move(TDBU, {S: 0.3})
    await gateway.wait_for_stream()
    await until(lambda: _position(hass, TOP_COVER) == 30)
    assert state(hass, TOP_COVER).state != STATE_UNAVAILABLE


async def test_a_shade_the_gateway_reports_offline_is_unavailable_until_it_is_back(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.set_online(BOTTOM_UP, False)
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == STATE_UNAVAILABLE)
    assert state(hass, TOP_COVER).state != STATE_UNAVAILABLE
    gateway.set_online(BOTTOM_UP, True)
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == "open")


async def test_events_of_other_kinds_and_other_shades_change_nothing(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    gateway.emit(EventKind.BATTERY_ALERT, TDBU, batteryLevel=1)
    gateway.emit(EventKind.MOTION_STARTED, 999, targetPositions={"primary": 1})
    gateway.set_online(BOTTOM_UP, False)
    await until(lambda: state(hass, BOTTOM_UP_COVER).state == STATE_UNAVAILABLE)
    assert not loaded.trackers[TDBU].moving
    assert loaded.trackers[TDBU].current[S] == 0.71


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
