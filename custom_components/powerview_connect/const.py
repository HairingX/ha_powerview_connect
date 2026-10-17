"""Constants for the PowerView Connect integration."""

from typing import Final

DOMAIN: Final = "powerview_connect"
MANUFACTURER: Final = "Hunter Douglas"

CONF_MOTION_POLL_INTERVAL: Final = "motion_poll_interval"
CONF_REFRESH_MINUTES: Final = "refresh_minutes"
DEFAULT_MOTION_POLL_INTERVAL: Final = 1.0
"""Seconds between two reads of a moving shade: it reports a new position about once a second."""
DEFAULT_REFRESH_MINUTES: Final = 10
"""Minutes between two reads of the whole home, in case an event was missed."""

CONF_RAISE_STALLED: Final = "raise_stalled"
CONF_STALL_PAUSE: Final = "stall_pause"
CONF_STALL_MIN_POSITION: Final = "stall_min_position"
DEFAULT_RAISE_STALLED: Final = False
DEFAULT_STALL_PAUSE: Final = 10.0
"""Seconds to wait after each step that raises a curtain the rest of the way."""
DEFAULT_STALL_MIN_POSITION: Final = 80
"""The lowest position, in percent, at which a curtain sent fully open counts as stuck."""

EVENT_SHADE_STALLED: Final = f"{DOMAIN}_shade_stalled"

SERVICE_SET_POSITIONS: Final = "set_positions"
ATTR_TOP: Final = "top"
ATTR_BOTTOM: Final = "bottom"
