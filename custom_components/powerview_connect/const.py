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

DEFAULT_RETRY_DELAY: Final = 300.0
"""Seconds a shade must be still before each attempt of a retry, and is held below the top."""

EVENT_SHADE_STALLED: Final = f"{DOMAIN}_shade_stalled"

SERVICE_SET_POSITIONS: Final = "set_positions"
ATTR_TOP: Final = "top"
ATTR_BOTTOM: Final = "bottom"
