"""Constants for the PowerView Gen 3 integration."""

from typing import Final

DOMAIN: Final = "powerview_connect"
MANUFACTURER: Final = "Hunter Douglas"

CONF_MOTION_POLL_INTERVAL: Final = "motion_poll_interval"
CONF_REFRESH_MINUTES: Final = "refresh_minutes"
DEFAULT_MOTION_POLL_INTERVAL: Final = 1.0
"""Seconds between two reads of a moving shade: it reports a new position about once a second."""
DEFAULT_REFRESH_MINUTES: Final = 10
"""Minutes between two reads of the whole home, in case an event was missed."""

SSE_IDLE_TIMEOUT: Final = 360.0
"""Seconds the event stream may stay silent before it is reopened; it is silent while nothing
moves, so this only catches a stream that broke without closing."""
SSE_BACKOFF: Final[tuple[float, ...]] = (1, 2, 5, 10, 30, 60)
"""Seconds to wait before each new attempt at the event stream, the last one repeated."""
MAX_CONCURRENT_POLLS: Final = 3
"""Reads of moving shades sent to the gateway at once."""

SERVICE_SET_POSITIONS: Final = "set_positions"
ATTR_TOP: Final = "top"
ATTR_BOTTOM: Final = "bottom"
