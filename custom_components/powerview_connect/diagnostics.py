"""What a bug report needs: the home as the hub knows it, without identities."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .runtime import PowerViewConfigEntry

REDACTED = "**REDACTED**"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PowerViewConfigEntry
) -> dict[str, Any]:
    """The hub's snapshot of the home, which leaves out addresses, serial numbers and Bluetooth
    names, and the entry without its address.

    The entry's unique id is left out: it is the gateway's serial number.
    """
    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": {key: REDACTED if key == CONF_HOST else value
                     for key, value in entry.data.items()},
            "options": dict(entry.options),
        },
        "hub": entry.runtime_data.hub.snapshot(),
    }
