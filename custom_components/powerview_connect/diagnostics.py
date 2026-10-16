"""What a bug report needs: the gateway, every shade and its motion, without identities."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from powerview_connect import GatewayStatus, Shade, ShadeTracker

from .hub import PowerViewConfigEntry

REDACTED = "**REDACTED**"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PowerViewConfigEntry
) -> dict[str, Any]:
    """The hub's picture of the home, without addresses, serial numbers or Bluetooth names.

    The entry's unique id is left out: it is the gateway's serial number.
    """
    hub = entry.runtime_data
    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": {key: REDACTED if key == CONF_HOST else value
                     for key, value in entry.data.items()},
            "options": dict(entry.options),
        },
        "available": hub.available,
        "stream_connected": hub.stream_connected,
        "gateways": [
            {"primary": gateway.is_primary, "model": gateway.model, "firmware": gateway.firmware,
             "radio_firmware": list(gateway.radio_firmware), "shades": list(gateway.shade_ids),
             "status": _status(hub.gateway_states.get(gateway.serial), gateway.serial in hub.gateway_states)}
            for gateway in hub.home.gateways
        ],
        "shades": {
            str(shade_id): _shade(shade, hub.trackers[shade_id])
            for shade_id, shade in hub.home.shades.items()
        },
        "scenes": len(hub.home.scenes),
    }


def _shade(shade: Shade, tracker: ShadeTracker) -> dict[str, Any]:
    return {
        "capabilities": shade.capabilities,
        "type": shade.type,
        "power_type": shade.power_type,
        "firmware": shade.firmware,
        "room": shade.room_name,
        "signal_strength": shade.signal_strength,
        "battery_status": shade.battery_status,
        "positions": {str(rail): value for rail, value in shade.positions.items()},
        "tracker": {
            "moving": tracker.moving,
            "online": tracker.online,
            "current": {str(rail): value for rail, value in tracker.current.items()},
            "target": {str(rail): value for rail, value in tracker.target.items()},
            "eta": tracker.eta,
        },
    }


def _status(status: GatewayStatus | None, asked: bool) -> dict[str, Any] | str:
    if status is None:
        return "not answering" if asked else "not asked"
    return {
        "hardware_version": status.hardware_version,
        "firmware": status.firmware,
        "radio_firmware": list(status.radio_firmware),
        "primary": status.is_primary,
        "interface": status.interface,
        "internet_state": status.internet_state,
    }
