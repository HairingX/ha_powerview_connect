"""Every kind of shade the Gen 3 API describes, as covers: rails, vanes, and which is which."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from homeassistant.components.cover import CoverEntityFeature, CoverState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from powerview_connect import Capabilities
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerview_connect.const import DOMAIN, SERVICE_SET_POSITIONS
from custom_components.powerview_connect.runtime import PowerViewRuntime

from .conftest import P, S, T, state, until

POSITION = (CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION | CoverEntityFeature.STOP)
TILT = (CoverEntityFeature.OPEN_TILT | CoverEntityFeature.CLOSE_TILT
        | CoverEntityFeature.SET_TILT_POSITION | CoverEntityFeature.STOP_TILT)

SHADES: dict[int, tuple[str, Capabilities]] = {
    701: ("Tilt 90", Capabilities.BOTTOM_UP_TILT_90),
    702: ("Tilt 180", Capabilities.BOTTOM_UP_TILT_180),
    703: ("Vertical", Capabilities.VERTICAL),
    704: ("Vertical Tilt", Capabilities.VERTICAL_TILT_180),
    708: ("Duolite", Capabilities.DUAL_OVERLAPPED),
    709: ("Duolite Tilt", Capabilities.DUAL_OVERLAPPED_TILT_90),
    710: ("Duolite Wide", Capabilities.DUAL_OVERLAPPED_TILT_180),
}


@pytest.fixture
async def kinds(
    hass: HomeAssistant, gateway: SimulatedGateway, config_entry: MockConfigEntry
) -> AsyncIterator[PowerViewRuntime]:
    """The home with one shade of each kind besides those in every test's home."""
    gateway.add_room(70, "Study")
    for shade_id, (name, capability) in SHADES.items():
        gateway.add_shade(shade_id, name, room_id=70, capabilities=capability,
                          positions={P: 0.2, S: 0.6, T: 0.4})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await gateway.wait_for_stream()
    yield config_entry.runtime_data
    await hass.config_entries.async_unload(config_entry.entry_id)


def _features(hass: HomeAssistant, entity_id: str) -> CoverEntityFeature:
    return CoverEntityFeature(state(hass, entity_id).attributes["supported_features"])


@pytest.mark.parametrize(("entity_id", "features", "device_class"), [
    ("cover.study_tilt_90", POSITION | TILT, "shade"),
    ("cover.study_tilt_180", POSITION | TILT, "shade"),
    ("cover.study_vertical", POSITION, "curtain"),
    ("cover.study_vertical_tilt", POSITION | TILT, "curtain"),
    ("cover.study_duolite_front", POSITION, "shade"),
    ("cover.study_duolite_rear", POSITION, "shade"),
    ("cover.study_duolite_tilt_front", POSITION | TILT, "shade"),
    ("cover.study_duolite_tilt_rear", POSITION, "shade"),
    ("cover.study_duolite_wide_front", POSITION | TILT, "shade"),
    ("cover.bedroom_blind", TILT, "shade"),
])
async def test_each_kind_of_shade_has_the_covers_its_capabilities_describe(
    hass: HomeAssistant, kinds: PowerViewRuntime, entity_id: str,
    features: CoverEntityFeature, device_class: str,
) -> None:
    assert _features(hass, entity_id) == features
    assert state(hass, entity_id).attributes["device_class"] == device_class


async def test_a_dual_overlapped_shade_shows_front_and_rear_rails_and_front_vanes(
    hass: HomeAssistant, kinds: PowerViewRuntime
) -> None:
    front = state(hass, "cover.study_duolite_tilt_front").attributes
    rear = state(hass, "cover.study_duolite_tilt_rear").attributes
    assert (front["current_position"], front["current_tilt_position"]) == (20, 40)
    assert rear["current_position"] == 60 and "current_tilt_position" not in rear


async def _call(hass: HomeAssistant, service: str, entity_id: str, **data: Any) -> None:
    await hass.services.async_call(
        "cover", service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True)


@pytest.mark.parametrize(("entity_id", "service", "data", "sent"), [
    ("cover.study_tilt_180", "set_cover_tilt_position", {"tilt_position": 70}, {"tilt": 0.7}),
    ("cover.study_tilt_180", "open_cover_tilt", {}, {"tilt": 1.0}),
    ("cover.study_tilt_180", "close_cover_tilt", {}, {"tilt": 0.0}),
    ("cover.study_tilt_180", "set_cover_position", {"position": 50}, {"primary": 0.5}),
    ("cover.study_duolite_front", "set_cover_position", {"position": 30}, {"primary": 0.3}),
    ("cover.study_duolite_rear", "close_cover", {}, {"secondary": 0.0}),
    ("cover.study_duolite_wide_front", "open_cover_tilt", {}, {"tilt": 1.0}),
])
async def test_a_command_sends_only_its_own_rail_or_the_vanes(
    hass: HomeAssistant, kinds: PowerViewRuntime, gateway: SimulatedGateway,
    entity_id: str, service: str, data: dict[str, Any], sent: dict[str, float],
) -> None:
    await _call(hass, service, entity_id, **data)
    moves = [r.body for r in gateway.requests if r.path == "/home/shades/positions"]
    assert moves == [{"positions": sent}]


async def test_stopping_the_vanes_stops_the_shade(
    hass: HomeAssistant, kinds: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    await _call(hass, "stop_cover_tilt", "cover.study_tilt_90")
    assert gateway.requests[-1].path == "/home/shades/stop"
    assert gateway.requests[-1].query == {"ids": "701"}


async def test_a_tilt_only_shade_is_closed_with_its_vanes_and_follows_their_move(
    hass: HomeAssistant, kinds: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    blind = "cover.bedroom_blind"
    await _call(hass, "close_cover_tilt", blind)
    assert state(hass, blind).state == CoverState.CLOSING
    gateway.finish(400)
    await until(lambda: state(hass, blind).state == CoverState.CLOSED)
    assert state(hass, blind).attributes["current_tilt_position"] == 0


async def test_set_positions_is_for_top_down_bottom_up_shades_only(
    hass: HomeAssistant, kinds: PowerViewRuntime
) -> None:
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_POSITIONS,
            {ATTR_ENTITY_ID: "cover.study_duolite_front", "top": 10}, blocking=True)
    assert raised.value.translation_key == "not_top_down_bottom_up"
