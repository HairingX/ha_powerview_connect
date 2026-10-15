"""A simulated PowerView gateway behind the integration, and a config entry for it.

The integration runs the real client against the library's simulated gateway, an HTTP server on
127.0.0.1 that answers as a real Gen 3 gateway was measured to. Shades move only when a test
moves them, and the motion clock moves only when a test advances it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator

import pytest
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, State
from powerview_connect import Capabilities, Rail
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerview_connect.const import DOMAIN
from custom_components.powerview_connect.hub import PowerViewHub

SERIAL = "SIMULATED-0001"
"""The simulated primary gateway's serial number, which is the entry's unique id."""
TITLE = "PowerView Simulated Gateway"

TDBU = 154
"""A top-down/bottom-up shade: its top rail at 0.71, its bottom rail down."""
BOTTOM_UP = 271
TOP_DOWN = 300
TILT_ONLY = 400
SCENE = 216

P, S, T = Rail.PRIMARY, Rail.SECONDARY, Rail.TILT


def furnish(gateway: SimulatedGateway) -> None:
    """A home of two rooms, one shade of each kind the integration tells apart, and a scene."""
    gateway.add_room(65, "Living Room")
    gateway.add_room(66, "Bedroom")
    gateway.add_shade(TDBU, "Kitchen Window", room_id=65,
                      capabilities=Capabilities.TOP_DOWN_BOTTOM_UP, shade_type=8,
                      positions={S: 0.71}, serial="0000000000000154")
    gateway.add_shade(BOTTOM_UP, "Patio Door", room_id=65, positions={P: 0.4})
    gateway.add_shade(TOP_DOWN, "Skylight", room_id=66, capabilities=Capabilities.TOP_DOWN,
                      positions={P: 0.25})
    gateway.add_shade(TILT_ONLY, "Blind", room_id=66, capabilities=Capabilities.TILT_ONLY_180,
                      positions={T: 0.5}, signal_strength=None)
    gateway.add_scene(SCENE, "Morning", room_id=65, members={TDBU: {P: 0.0, S: 0.0}})


class FakeClock:
    """A monotonic clock that moves only when a test advances it."""

    def __init__(self) -> None:
        """A clock at 1000 s."""
        self.now = 1000.0

    def __call__(self) -> float:
        """The time, in seconds."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the clock on."""
        self.now += seconds


def state(hass: HomeAssistant, entity_id: str) -> State:
    """The state of `entity_id`, which must exist."""
    found = hass.states.get(entity_id)
    assert found is not None, entity_id
    return found


async def until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Wait until `condition` holds, as an event from the gateway takes a moment to arrive."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def no_deprecated_usage(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail a test in which Home Assistant reports this integration using something deprecated."""
    yield
    reports = [
        record.getMessage()
        for phase in ("setup", "call")
        for record in caplog.get_records(phase)
        if "custom integration 'powerview_connect'" in record.getMessage()
    ]
    assert reports == []


@pytest.fixture(autouse=True)
def quick_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """The event stream is reopened at once, rather than after seconds."""
    monkeypatch.setattr("custom_components.powerview_connect.hub.SSE_BACKOFF", (0.05,))


@pytest.fixture
async def gateway(socket_enabled: None) -> AsyncIterator[SimulatedGateway]:
    """The simulated gateway, started, with its home furnished.

    It and the integration talk over 127.0.0.1, the only host the tests may reach.
    """
    simulated = SimulatedGateway(name="Simulated Gateway")
    furnish(simulated)
    async with simulated:
        yield simulated


@pytest.fixture
def every_entity_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every entity is enabled when it is first added, those disabled by default too."""
    monkeypatch.setattr(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        property(lambda _: True),
    )


@pytest.fixture
def config_entry(gateway: SimulatedGateway) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title=TITLE, unique_id=SERIAL, data={CONF_HOST: gateway.host}
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def loaded(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedGateway, clock: FakeClock
) -> AsyncIterator[PowerViewHub]:
    """The config entry, set up and listening to the event stream; unloaded after the test."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    hub: PowerViewHub = config_entry.runtime_data
    hub.clock = clock
    await gateway.wait_for_stream()
    await until(lambda: hub.stream_connected)
    yield hub
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
