"""A bug report's diagnostics: complete, without addresses, serial numbers or Bluetooth names."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from powerview_connect.testing import SimulatedGateway

from custom_components.powerview.diagnostics import async_get_config_entry_diagnostics
from custom_components.powerview.hub import PowerViewHub

from .conftest import SERIAL, TDBU


async def test_diagnostics_hold_every_shade_but_no_address_or_identity(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway
) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, loaded.entry)
    text = json.dumps(diagnostics)  # raises for anything JSON cannot hold
    for secret in (gateway.host, "127.0.0.1", SERIAL, "0000000000000154", "SIM:", "simulated-home"):
        assert secret not in text, secret
    assert diagnostics["available"] is True and diagnostics["stream_connected"] is True
    assert diagnostics["gateways"] == [{"primary": True, "model": "Pro", "firmware": "3.2.59"}]
    shade = diagnostics["shades"][str(TDBU)]
    assert shade["capabilities"] == 7 and shade["room"] == "Living Room"
    assert shade["tracker"]["current"] == {"primary": 0.0, "secondary": 0.71, "tilt": 0.0}
    assert shade["tracker"]["moving"] is False
    assert diagnostics["scenes"] == 1
