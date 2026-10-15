"""How well the gateway hears each shade."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.powerview_connect.hub import PowerViewHub

from .conftest import BOTTOM_UP, TDBU, FakeClock, P, state, until

KITCHEN = "sensor.living_room_kitchen_window_signal_strength"
PATIO = "sensor.living_room_patio_door_signal_strength"


async def test_the_signal_strength_is_a_diagnostic_disabled_until_asked_for(
    hass: HomeAssistant, loaded: PowerViewHub
) -> None:
    entry = er.async_get(hass).async_get(KITCHEN)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert hass.states.get(KITCHEN) is None


async def test_a_shade_the_gateway_reports_no_signal_strength_for_has_no_sensor(
    hass: HomeAssistant, loaded: PowerViewHub
) -> None:
    assert er.async_get(hass).async_get("sensor.bedroom_blind_signal_strength") is None


async def test_the_signal_strength_is_the_gateways_in_dbm(
    hass: HomeAssistant, every_entity_enabled: None, loaded: PowerViewHub
) -> None:
    kitchen = state(hass, KITCHEN)
    assert kitchen.state == "-66"
    assert kitchen.attributes["unit_of_measurement"] == SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    assert kitchen.attributes["device_class"] == SensorDeviceClass.SIGNAL_STRENGTH
    assert kitchen.attributes["state_class"] == SensorStateClass.MEASUREMENT


async def test_the_signal_strength_follows_each_read_of_the_home(
    hass: HomeAssistant, every_entity_enabled: None, loaded: PowerViewHub,
    gateway: SimulatedGateway,
) -> None:
    gateway.shades[TDBU].signal_strength = -80
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=10))
    await hass.async_block_till_done()
    await until(lambda: state(hass, KITCHEN).state == "-80")
    assert state(hass, PATIO).state == "-66"


async def test_the_signal_strength_follows_the_reads_of_a_moving_shade(
    hass: HomeAssistant, every_entity_enabled: None, loaded: PowerViewHub,
    gateway: SimulatedGateway, clock: FakeClock,
) -> None:
    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.living_room_patio_door"}, blocking=True)
    gateway.shades[BOTTOM_UP].signal_strength = -58
    gateway.move(BOTTOM_UP, {P: 0.5})
    clock.advance(1)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert state(hass, PATIO).state == "-58"


async def test_the_signal_strength_is_unavailable_with_the_gateway(
    hass: HomeAssistant, every_entity_enabled: None, loaded: PowerViewHub,
    gateway: SimulatedGateway,
) -> None:
    await gateway.close()
    await until(lambda: state(hass, KITCHEN).state == "unavailable")
