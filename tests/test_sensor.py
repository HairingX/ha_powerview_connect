"""How well the gateway hears each shade."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from powerview_connect.testing import ManualClock, SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerview_connect.runtime import PowerViewRuntime

from .conftest import BOTTOM_UP, ON_BATTERY, TDBU, P, state, tick_until, until

KITCHEN = "sensor.living_room_kitchen_window_signal_strength"
PATIO = "sensor.living_room_patio_door_signal_strength"


async def test_the_signal_strength_is_a_diagnostic_disabled_until_asked_for(
    hass: HomeAssistant, loaded: PowerViewRuntime
) -> None:
    entry = er.async_get(hass).async_get(KITCHEN)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert hass.states.get(KITCHEN) is None


async def test_a_shade_the_gateway_reports_no_signal_strength_for_has_no_sensor(
    hass: HomeAssistant, loaded: PowerViewRuntime
) -> None:
    assert er.async_get(hass).async_get("sensor.bedroom_blind_signal_strength") is None


async def test_the_signal_strength_is_the_gateways_in_dbm(
    hass: HomeAssistant, every_entity_enabled: None, loaded: PowerViewRuntime
) -> None:
    kitchen = state(hass, KITCHEN)
    assert kitchen.state == "-66"
    assert kitchen.attributes["unit_of_measurement"] == SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    assert kitchen.attributes["device_class"] == SensorDeviceClass.SIGNAL_STRENGTH
    assert kitchen.attributes["state_class"] == SensorStateClass.MEASUREMENT


async def test_the_signal_strength_follows_each_read_of_the_home(
    hass: HomeAssistant, every_entity_enabled: None, loaded: PowerViewRuntime,
    gateway: SimulatedGateway, clock: ManualClock,
) -> None:
    gateway.shades[TDBU].signal_strength = -80
    await clock.advance(600)
    await until(lambda: state(hass, KITCHEN).state == "-80")
    assert state(hass, PATIO).state == "-66"


async def test_the_signal_strength_follows_the_reads_of_a_moving_shade(
    hass: HomeAssistant, every_entity_enabled: None, loaded: PowerViewRuntime,
    gateway: SimulatedGateway, clock: ManualClock,
) -> None:
    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.living_room_patio_door"}, blocking=True)
    gateway.shades[BOTTOM_UP].signal_strength = -58
    gateway.move(BOTTOM_UP, {P: 0.5})
    await tick_until(clock, lambda: state(hass, PATIO).state == "-58")


async def test_the_signal_strength_is_unavailable_with_the_gateway(
    hass: HomeAssistant, every_entity_enabled: None, loaded: PowerViewRuntime,
    gateway: SimulatedGateway, clock: ManualClock,
) -> None:
    await gateway.close()
    await tick_until(clock, lambda: state(hass, KITCHEN).state == "unavailable")


BATTERY_LEVEL = "sensor.bedroom_roller_battery_level"
LOW_BATTERY = "binary_sensor.bedroom_roller_battery"


async def test_only_a_shade_off_mains_power_has_battery_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime
) -> None:
    """A hard-wired shade reports a battery status too, which means nothing there."""
    registry = er.async_get(hass)
    battery_entities = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, config_entry.entry_id)
        if entity.unique_id.endswith(("_battery_level", "_battery_low"))
    ]
    assert sorted(battery_entities) == [LOW_BATTERY, BATTERY_LEVEL]


async def test_a_shade_off_mains_power_shows_its_battery_level_and_whether_it_is_low(
    hass: HomeAssistant, loaded: PowerViewRuntime
) -> None:
    level = state(hass, BATTERY_LEVEL)
    assert level.state == "medium"
    assert level.attributes["options"] == ["low", "medium", "high", "plugged_in"]
    entry = er.async_get(hass).async_get(BATTERY_LEVEL)
    assert entry is not None and entry.entity_category is EntityCategory.DIAGNOSTIC
    low = state(hass, LOW_BATTERY)
    assert (low.state, low.attributes["device_class"]) == ("off", "battery")


async def test_a_low_battery_is_shown_at_the_next_read_of_the_home(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    gateway.shades[ON_BATTERY].battery_status = 1
    await loaded.hub.refresh()
    assert state(hass, BATTERY_LEVEL).state == "low"
    assert state(hass, LOW_BATTERY).state == "on"


async def test_a_battery_status_not_known_is_shown_unknown(
    hass: HomeAssistant, loaded: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    for status in (0, 9):
        gateway.shades[ON_BATTERY].battery_status = status
        await loaded.hub.refresh()
        assert state(hass, BATTERY_LEVEL).state == "unknown"
        assert state(hass, LOW_BATTERY).state == "unknown"
