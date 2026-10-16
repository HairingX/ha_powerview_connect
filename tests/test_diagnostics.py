"""A bug report's diagnostics: complete, without addresses, serial numbers or Bluetooth names."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerview_connect.diagnostics import async_get_config_entry_diagnostics
from custom_components.powerview_connect.runtime import PowerViewRuntime

from .conftest import SERIAL, TDBU


async def test_diagnostics_hold_every_shade_but_no_address_or_identity(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime,
    gateway: SimulatedGateway,
) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    text = json.dumps(diagnostics)  # raises for anything JSON cannot hold
    for secret in (gateway.host, "127.0.0.1", SERIAL, "0000000000000154", "SIM:", "simulated-home"):
        assert secret not in text, secret
    assert diagnostics["entry"]["data"] == {"host": "**REDACTED**"}
    hub = diagnostics["hub"]
    assert hub["connection"] == "connected" and hub["stream_open"] is True
    (primary,) = hub["gateways"]
    assert (primary["primary"], primary["model"], primary["firmware"], primary["reachable"]) == (
        True, "Pro", "3.2.59", True)
    assert primary["status"]["hardware_version"] == "3.0.4"
    shade = hub["shades"][str(TDBU)]
    assert shade["capabilities"] == 7 and shade["room"] == "Living Room"
    assert shade["positions"] == {"primary": 0.0, "secondary": 0.71, "tilt": 0.0}
    assert shade["moving"] is False
    assert hub["scenes"] == 1
