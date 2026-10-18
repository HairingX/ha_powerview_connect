"""Constants for the PowerView Connect integration."""

from typing import Final

from powerview_connect import RetryOutcome

DOMAIN: Final = "powerview_connect"
MANUFACTURER: Final = "Hunter Douglas"

CONF_MOTION_POLL_INTERVAL: Final = "motion_poll_interval"
CONF_REFRESH_MINUTES: Final = "refresh_minutes"
DEFAULT_MOTION_POLL_INTERVAL: Final = 1.0
"""Seconds between two reads of a moving shade: it reports a new position about once a second."""
DEFAULT_REFRESH_MINUTES: Final = 10
"""Minutes between two reads of the whole home, in case an event was missed."""

DEFAULT_RETRY_DELAY: Final = 90.0
"""Seconds to let the fabric settle after each step that retries a stalled opening."""
DEFAULT_RETRY_ABOVE: Final = 80
"""The lowest position, in percent, at which an opening that stops counts as stalled."""

EVENT_SHADE_STALLED: Final = f"{DOMAIN}_shade_stalled"
STALL_OUTCOMES: Final[dict[RetryOutcome, str]] = {
    RetryOutcome.STARTED: "started",
    RetryOutcome.OPENED: "opened",
    RetryOutcome.GAVE_UP: "gave_up",
    RetryOutcome.INTERRUPTED: "interrupted",
}
"""The stalled event's `outcome` for each outcome of a retry; one not listed fires no event."""

SERVICE_SET_POSITIONS: Final = "set_positions"
ATTR_TOP: Final = "top"
ATTR_BOTTOM: Final = "bottom"
