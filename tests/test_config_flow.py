"""Adding a home by its primary gateway, finding one on the network, and changing its address."""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any

import pytest
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    SOURCE_ZEROCONF,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerview_connect.const import DOMAIN
from custom_components.powerview_connect.runtime import PowerViewRuntime

from .conftest import SERIAL, TITLE


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "user"
    return result["flow_id"]


async def _submit(hass: HomeAssistant, flow_id: str, user_input: dict[str, Any]) -> ConfigFlowResult:
    # HA declares the flow manager's user input as a bare `dict`.
    flow: Any = hass.config_entries.flow
    result: ConfigFlowResult = await flow.async_configure(flow_id, user_input)
    return result


def _discovery(gateway: SimulatedGateway, port: int | None = None) -> ZeroconfServiceInfo:
    address, gateway_port = gateway.host.split(":")
    return ZeroconfServiceInfo(
        ip_address=ip_address(address),
        ip_addresses=[ip_address(address)],
        port=int(gateway_port) if port is None else port,
        hostname="powerview-g3.local.",
        type="_PowerView-G3._tcp.local.",
        name="Simulated Gateway._PowerView-G3._tcp.local.",
        properties={},
    )


async def _discover(hass: HomeAssistant, info: ZeroconfServiceInfo) -> ConfigFlowResult:
    result: ConfigFlowResult = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=info
    )
    return result


async def _reconfigure(hass: HomeAssistant, entry: ConfigEntry) -> ConfigFlowResult:
    result: ConfigFlowResult = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    return result


async def _unload_all(hass: HomeAssistant) -> None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)


async def test_a_home_is_added_by_its_primary_gateways_serial_number(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    flow = await _start(hass)
    result = await _submit(hass, flow, {CONF_HOST: f"  {gateway.host} "})
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("title") == TITLE
    assert result.get("data") == {CONF_HOST: gateway.host}
    entry = result.get("result")
    assert isinstance(entry, ConfigEntry)
    assert entry.unique_id == SERIAL
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    await _unload_all(hass)


async def test_an_address_where_no_gateway_answers_is_reported_and_can_be_corrected(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    host = gateway.host
    await gateway.close()
    flow = await _start(hass)
    result = await _submit(hass, flow, {CONF_HOST: host})
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {"base": "cannot_connect"}
    await gateway.start()
    result = await _submit(hass, flow, {CONF_HOST: host})
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    await _unload_all(hass)


async def test_an_empty_host_is_refused_before_anything_is_sent(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    flow = await _start(hass)
    result = await _submit(hass, flow, {CONF_HOST: "  "})
    assert result.get("errors") == {"base": "invalid_host"}
    assert gateway.requests == []


async def test_an_auxiliary_gateway_is_refused_and_the_primary_one_named(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    gateway.gateways[0].aux = True
    gateway.add_gateway("PRIMARY-1", "Hall Gateway", ip="192.0.2.10", aux=False)
    flow = await _start(hass)
    result = await _submit(hass, flow, {CONF_HOST: gateway.host})
    assert result.get("errors") == {"base": "not_primary"}
    assert result.get("description_placeholders") == {"primary": "192.0.2.10"}


async def test_a_home_whose_gateways_list_no_primary_one_is_not_a_gateway(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    gateway.gateways[0].aux = True
    flow = await _start(hass)
    result = await _submit(hass, flow, {CONF_HOST: gateway.host})
    assert result.get("errors") == {"base": "cannot_connect"}


async def test_a_home_without_shades_is_refused(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    gateway.shades.clear()
    flow = await _start(hass)
    result = await _submit(hass, flow, {CONF_HOST: gateway.host})
    assert result.get("errors") == {"base": "no_shades"}


async def test_a_home_already_added_moves_to_the_address_given(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: "192.0.2.1"})
    entry.add_to_hass(hass)
    flow = await _start(hass)
    result = await _submit(hass, flow, {CONF_HOST: gateway.host})
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "already_configured"
    assert entry.data == {CONF_HOST: gateway.host}


async def test_a_discovered_gateway_is_offered_and_added(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    result = await _discover(hass, _discovery(gateway))
    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "discovery_confirm"
    assert result.get("description_placeholders") == {"name": TITLE, "host": gateway.host}
    result = await _submit(hass, result["flow_id"], {})
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("data") == {CONF_HOST: gateway.host}
    await hass.async_block_till_done()
    await _unload_all(hass)


async def test_a_gateway_discovered_at_the_http_port_is_reached_without_one(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    """Nothing answers at 127.0.0.1:80 in a test, which shows the port was left out."""
    result = await _discover(hass, _discovery(gateway, port=80))
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "cannot_connect"


async def test_a_discovered_auxiliary_gateway_is_not_offered(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    gateway.gateways[0].aux = True
    gateway.add_gateway("PRIMARY-1", "Hall Gateway", ip="192.0.2.10", aux=False)
    result = await _discover(hass, _discovery(gateway))
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "not_primary"


async def test_a_configured_home_discovered_at_a_new_address_moves_there(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: "192.0.2.1"})
    entry.add_to_hass(hass)
    result = await _discover(hass, _discovery(gateway))
    assert result.get("reason") == "already_configured"
    assert entry.data == {CONF_HOST: gateway.host}


async def test_a_gateway_discovered_where_a_home_is_configured_is_not_read(
    hass: HomeAssistant, gateway: SimulatedGateway
) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: gateway.host}).add_to_hass(hass)
    result = await _discover(hass, _discovery(gateway))
    assert result.get("reason") == "already_configured"
    assert gateway.requests == []


async def test_reconfiguring_moves_the_home_to_its_gateways_new_address(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    entry = config_entry
    result = await _reconfigure(hass, entry)
    assert result.get("step_id") == "reconfigure"
    result = await _submit(hass, result["flow_id"], {CONF_HOST: "127.0.0.1:1"})
    assert result.get("errors") == {"base": "cannot_connect"}
    result = await _submit(hass, result["flow_id"], {CONF_HOST: f"http://{gateway.host}/"})
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "reconfigure_successful"
    assert entry.data == {CONF_HOST: gateway.host}
    await hass.async_block_till_done()


async def test_reconfiguring_to_another_homes_gateway_is_refused(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime, gateway: SimulatedGateway
) -> None:
    async with SimulatedGateway(serial="OTHER-0002") as other:
        other.add_room(1, "Room")
        other.add_shade(1, "Shade", room_id=1)
        result = await _reconfigure(hass, config_entry)
        result = await _submit(hass, result["flow_id"], {CONF_HOST: other.host})
    assert result.get("reason") == "wrong_gateway"
    assert config_entry.data == {CONF_HOST: gateway.host}


@pytest.mark.parametrize(("given", "stored"), [
    ({}, {"motion_poll_interval": 1.0, "refresh_minutes": 10}),
    ({"motion_poll_interval": "2.5", "refresh_minutes": 30},
     {"motion_poll_interval": 2.5, "refresh_minutes": 30}),
])
async def test_the_options_are_stored_and_the_home_reloaded(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime, given: dict[str, Any], stored: dict[str, Any]
) -> None:
    entry = config_entry
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result.get("step_id") == "init"
    flow: Any = hass.config_entries.options
    result = await flow.async_configure(result["flow_id"], given)
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == stored
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not loaded


async def test_the_options_refuse_a_read_more_often_than_twice_a_second(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: PowerViewRuntime
) -> None:
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    flow: Any = hass.config_entries.options
    with pytest.raises(Exception, match="motion_poll_interval"):
        await flow.async_configure(result["flow_id"], {"motion_poll_interval": 0.1})
