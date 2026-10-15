"""Constants for the PowerView Gen 3 (unofficial) integration."""

from typing import Final

DOMAIN: Final = "powerview"
MANUFACTURER: Final = "Hunter Douglas"

# Options
CONF_MOTION_POLL_INTERVAL: Final = "motion_poll_interval"
CONF_REFRESH_MINUTES: Final = "refresh_minutes"
DEFAULT_MOTION_POLL_INTERVAL: Final = 1.0  # seconds between polls while a shade moves
DEFAULT_REFRESH_MINUTES: Final = 10  # full state refresh as a safety net

# The gateway's SSE stream is silent while nothing moves. If no bytes arrive for
# this long, the stream is reopened (openHAB uses 360 s for the same purpose).
SSE_IDLE_TIMEOUT: Final = 360.0
SSE_BACKOFF: Final = (1, 2, 5, 10, 30, 60)

# Max concurrent position polls against the gateway.
MAX_CONCURRENT_POLLS: Final = 3

# Service
SERVICE_SET_POSITIONS: Final = "set_positions"
ATTR_TOP: Final = "top"
ATTR_BOTTOM: Final = "bottom"

# Shade capability numbers (Gen 3 "capabilities" field).
CAPABILITY_TOP_DOWN: Final = 6
CAPABILITY_TDBU: Final = 7
CAPABILITY_NAMES: Final = {
    0: "Bottom Up",
    1: "Bottom Up, Tilt 90°",
    2: "Bottom Up, Tilt 180°",
    3: "Vertical",
    4: "Vertical, Tilt 180°",
    5: "Tilt Only 180°",
    6: "Top Down",
    7: "Top Down Bottom Up",
    8: "Dual Overlapped",
    9: "Dual Overlapped, Tilt 90°",
    10: "Dual Overlapped, Tilt 180°",
    11: "Dual Overlapped (type 11)",
}


def signal_shade_update(entry_id: str, shade_id: int) -> str:
    """Dispatcher signal for one shade."""
    return f"{DOMAIN}_{entry_id}_shade_{shade_id}"


def signal_hub_availability(entry_id: str) -> str:
    """Dispatcher signal for gateway availability changes."""
    return f"{DOMAIN}_{entry_id}_available"
