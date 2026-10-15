"""The integration against a real PowerView Gen 3 gateway, read-only: added through its config
flow, loaded, every shade a cover, and unloaded again.

Skipped unless a gateway is configured, as the primary gateway's IP address:

    POWERVIEW_HOST=<gateway-ip>          (environment variable)
    POWERVIEW_HOST = "<gateway-ip>"      (in mysecrets.py, which is gitignored)

The client is read-only, so every command is refused before it reaches the gateway: nothing
here moves a shade. Only GET /home and the event stream are read.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from typing import Any

import pytest
import pytest_socket
from homeassistant.config_entries import SOURCE_USER, ConfigEntry, ConfigEntryState, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from powerview_connect import PowerViewClient

from custom_components.powerview.const import DOMAIN
from custom_components.powerview.hub import PowerViewHub

from .conftest import until


def _host() -> str | None:
    if host := os.environ.get("POWERVIEW_HOST"):
        return host
    try:
        secrets = importlib.import_module("mysecrets")
    except ModuleNotFoundError:
        return None
    found = getattr(secrets, "POWERVIEW_HOST", None)
    return found if isinstance(found, str) else None


HOST = _host()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(HOST is None, reason="no PowerView gateway configured (POWERVIEW_HOST)"),
]


@pytest.fixture
def read_only(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[PowerViewClient]]:
    """Every client the integration makes reaches the real gateway, read-only."""
    assert HOST is not None
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts([HOST.split(":")[0], "127.0.0.1"])
    made: list[PowerViewClient] = []

    def new_client(hass: HomeAssistant, host: str) -> PowerViewClient:
        client = PowerViewClient(async_get_clientsession(hass), host, read_only=True)
        made.append(client)
        return client

    monkeypatch.setattr("custom_components.powerview.hub.new_client", new_client)
    monkeypatch.setattr("custom_components.powerview.new_client", new_client)
    monkeypatch.setattr("custom_components.powerview.config_flow.new_client", new_client)
    yield made


async def test_a_real_gateway_is_added_and_every_shade_is_a_cover(
    hass: HomeAssistant, read_only: list[PowerViewClient]
) -> None:
    started = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    # HA declares the flow manager's user input as a bare `dict`.
    flow: Any = hass.config_entries.flow
    result: ConfigFlowResult = await flow.async_configure(started["flow_id"], {CONF_HOST: HOST})
    assert result.get("type") is FlowResultType.CREATE_ENTRY, result
    entry = result.get("result")
    assert isinstance(entry, ConfigEntry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    hub: PowerViewHub = entry.runtime_data
    assert all(client.read_only for client in read_only)
    await until(lambda: hub.stream_connected, timeout=15)
    covers = hass.states.async_all("cover")
    assert len(covers) >= len(hub.home.shades) > 0
    assert all(state.state != "unavailable" for state in covers)
    for state in covers:
        print(f"  {state.entity_id:48} {state.state:8} {state.attributes.get('current_position')}")

    assert await hass.config_entries.async_unload(entry.entry_id)
