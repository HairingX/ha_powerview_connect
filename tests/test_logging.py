"""The debug log: what a report of how the gateway behaves needs."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from powerview_connect import Home
from powerview_connect.testing import SimulatedGateway
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.powerview_connect.hub import PowerViewHub
from custom_components.powerview_connect.redact import Redactions

from .conftest import BOTTOM_UP, SERIAL, TDBU, P, S, until


def _ours(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records
                     if record.name.startswith("custom_components.powerview_connect"))


async def test_the_debug_log_holds_every_event_and_how_long_each_request_took(
    hass: HomeAssistant, loaded: PowerViewHub, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.powerview_connect")
    await loaded.async_move(BOTTOM_UP, {P: 0.6})
    await until(lambda: "Event: ShadeEvent(kind='motion-started', shade_id=271" in caplog.text)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1.1))
    await until(lambda: "Reading shade 271 took" in caplog.text)
    await loaded.async_refresh()
    for request in ("Moving shade 271 to {<Rail.PRIMARY: 'primary'>: 0.6}", "Reading the home"):
        assert f"{request} took" in caplog.text


async def test_the_log_holds_the_address_but_no_serial_number_or_bluetooth_name(
    hass: HomeAssistant, loaded: PowerViewHub, gateway: SimulatedGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.powerview_connect")
    gateway.command_errors[TDBU] = 7
    with pytest.raises(HomeAssistantError) as raised:
        await loaded.async_move(TDBU, {S: 0.2})
    assert "<shade 154>" in str(raised.value) and "SIM:" not in str(raised.value)
    await gateway.close()
    await loaded.async_refresh()
    await until(lambda: "does not answer" in _ours(caplog))
    logged = _ours(caplog)
    assert gateway.host in logged
    for secret in (SERIAL, "0000000000000154", "SIM:"):
        assert secret not in logged, secret


def test_longer_texts_are_replaced_first_and_an_empty_one_never() -> None:
    redactions = Redactions()
    redactions.add_home(Home(None, (), {}, ()))
    redactions.add("ABC", "<short>")
    redactions.add("ABCDEF", "<long>")
    redactions.add(None, "<nothing>")
    assert redactions.redact("ABCDEF ABC") == "<long> <short>"
