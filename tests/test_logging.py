"""The debug log: what a report of how the gateway behaves needs."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.powerview_connect.hub import PowerViewHub

from .conftest import BOTTOM_UP, P, until


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
