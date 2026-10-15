"""Per-shade motion tracking (no Home Assistant imports, no I/O).

Behaviour measured on a Gen 3 gateway (firmware 3.2.59, Duette TDBU, build 433):
- motion-started arrives ~immediately after a command, with targetPositions + etaInSeconds,
  for every source (HA, app, Google). The motor starts ~4-5 s later.
- etaInSeconds underestimates the real duration (~1.8-2.2x observed), so it is not used
  to decide when the shade has arrived.
- GET /home/shades/{id} reports intermediate positions while moving (~0.01 steps, ~1 s).
- motion-stopped carries the final positions; it is usually on time but was once ~14-23 s late.

So: SSE starts tracking, polling supplies live positions, and tracking ends on whichever
comes first: motion-stopped, target reached and stable, or motion stalled.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .model import RAILS, parse_positions

EPS = 0.005  # positions are reported in 0.01 steps


class ShadeTracker:
    """Track position, target and motion for one shade."""

    def __init__(
        self,
        positions: Mapping[str, float] | None = None,
        *,
        stall_seconds: float = 6.0,
        arrive_settle_seconds: float = 1.5,
        start_grace_seconds: float = 25.0,
        min_timeout_seconds: float = 90.0,
    ) -> None:
        """Initialise with the last known positions."""
        self.current: dict[str, float | None] = dict.fromkeys(RAILS)
        self.target: dict[str, float | None] = dict.fromkeys(RAILS)
        self.moving = False
        self.online = True
        self.eta: float | None = None
        self._stall = stall_seconds
        self._settle = arrive_settle_seconds
        self._start_grace = start_grace_seconds
        self._min_timeout = min_timeout_seconds
        self._started_at: float | None = None
        self._last_change_at: float | None = None
        self._changed_since_start = False
        self._last_delta: dict[str, float] = {}
        if positions:
            self._apply(positions)

    # ----- internal helpers -------------------------------------------------

    def _apply(self, positions: Mapping[str, Any]) -> bool:
        """Apply positions; return True if anything changed."""
        changed = False
        for rail, value in parse_positions(dict(positions)).items():
            old = self.current[rail]
            if old is None or abs(value - old) > 1e-9:
                if old is not None:
                    self._last_delta[rail] = value - old
                self.current[rail] = value
                changed = True
        return changed

    def _begin(self, now: float) -> None:
        self.moving = True
        self._started_at = now
        self._last_change_at = now
        self._changed_since_start = False
        self._last_delta = {}

    def _finish(self) -> None:
        self.moving = False
        self.target = dict.fromkeys(RAILS)
        self.eta = None
        self._started_at = None
        self._last_change_at = None
        self._changed_since_start = False

    def _reached(self) -> bool:
        known = [r for r in RAILS if self.target[r] is not None]
        return bool(known) and all(
            self.current[r] is not None and abs(self.current[r] - self.target[r]) <= EPS  # type: ignore[operator]
            for r in known
        )

    def _timeout(self) -> float:
        return max(self._min_timeout, (self.eta or 0) * 3 + 30)

    # ----- inputs -----------------------------------------------------------

    def snapshot(self, positions: Mapping[str, Any]) -> bool:
        """Apply a full-refresh snapshot. Ignored while moving (polling owns that)."""
        if self.moving:
            return False
        return self._apply(positions)

    def motion_started(self, event: Mapping[str, Any], now: float) -> None:
        """Handle an SSE motion-started event."""
        self._apply(event.get("currentPositions") or {})
        raw_target = event.get("targetPositions") or {}
        targets = parse_positions(raw_target)
        self._begin(now)
        if targets:
            self.target = {r: targets.get(r) for r in RAILS}
        eta = raw_target.get("etaInSeconds") if isinstance(raw_target, dict) else None
        self.eta = float(eta) if isinstance(eta, (int, float)) else None

    def motion_stopped(self, event: Mapping[str, Any]) -> None:
        """Handle an SSE motion-stopped event (authoritative final position)."""
        self._apply(event.get("currentPositions") or {})
        self._finish()

    def command(self, now: float, **targets: float | None) -> bool:
        """Record a command sent by HA. Return True if motion is expected."""
        updates = {r: float(v) for r, v in targets.items() if v is not None and r in RAILS}
        expect_motion = any(
            self.current[r] is None or abs(self.current[r] - v) > EPS  # type: ignore[operator]
            for r, v in updates.items()
        )
        if not expect_motion:
            return False
        if not self.moving:
            self.target = dict.fromkeys(RAILS)
            self._begin(now)
        else:
            # New command during motion: keep the other rail's target, restart the clocks.
            self._started_at = now
            self._last_change_at = now
        self.target.update(updates)
        return True

    def stop_requested(self, now: float) -> None:
        """A stop was sent: forget targets, keep tracking until the shade is still."""
        if self.moving:
            self.target = dict.fromkeys(RAILS)
            self._last_change_at = now

    def poll(self, positions: Mapping[str, Any], now: float) -> bool:
        """Apply a poll taken while moving. Return True to keep polling."""
        if not self.moving:
            return False
        if self._apply(positions):
            self._last_change_at = now
            self._changed_since_start = True
        assert self._started_at is not None and self._last_change_at is not None
        quiet_for = now - self._last_change_at
        if self._reached() and quiet_for >= self._settle:
            self._finish()
        elif self._changed_since_start and quiet_for >= self._stall:
            # Moved, then stopped short of the target (other rail, manual stop, ...).
            self._finish()
        elif not self._changed_since_start and now - self._started_at >= self._start_grace:
            # Nothing ever moved (no-op command or lost command).
            self._finish()
        elif now - self._started_at >= self._timeout():
            self._finish()
        return self.moving

    # ----- outputs ----------------------------------------------------------

    def direction(self, rail: str) -> int:
        """Return +1 (opening), -1 (closing) or 0 for a rail."""
        if not self.moving:
            return 0
        target, current = self.target.get(rail), self.current.get(rail)
        if target is not None and current is not None:
            if target > current + EPS:
                return 1
            if target < current - EPS:
                return -1
            return 0
        delta = self._last_delta.get(rail, 0.0)
        return (delta > 0) - (delta < 0)
