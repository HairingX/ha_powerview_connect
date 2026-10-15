"""Runtime for one PowerView Gen 3 gateway: SSE listener, motion polling, commands."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .api import STREAM_OPENED, PowerViewClient, PowerViewError
from .const import (
    MAX_CONCURRENT_POLLS,
    SSE_BACKOFF,
    SSE_IDLE_TIMEOUT,
    signal_hub_availability,
    signal_shade_update,
)
from .model import GatewayInfo, HomeData, ShadeInfo, parse_home
from .motion import ShadeTracker

_LOGGER = logging.getLogger(__name__)


class PowerViewHub:
    """Owns the state of all shades on one gateway."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PowerViewClient,
        home: HomeData,
        *,
        poll_interval: float,
        refresh_minutes: int,
    ) -> None:
        """Initialise from an already fetched /home document."""
        self.hass = hass
        self.entry = entry
        self.client = client
        self.home = home
        self.unique_id: str = entry.unique_id or (home.home_id or client.host)
        self.gateway: GatewayInfo | None = home.gateway_for_host(client.host) or home.primary_gateway
        self.shades: dict[int, ShadeInfo] = dict(home.shades)
        self.trackers: dict[int, ShadeTracker] = {
            sid: ShadeTracker(info.positions) for sid, info in home.shades.items()
        }
        self.available = True
        self.sse_connected = False
        self._poll_interval = poll_interval
        self._refresh_interval = timedelta(minutes=refresh_minutes)
        self._poll_tasks: dict[int, asyncio.Task[None]] = {}
        self._poll_sem = asyncio.Semaphore(MAX_CONCURRENT_POLLS)

    # ----- lifecycle --------------------------------------------------------

    @callback
    def async_start(self) -> None:
        """Start the SSE listener and the periodic safety refresh."""
        self.entry.async_create_background_task(
            self.hass, self._sse_loop(), f"powerview {self.client.host} events"
        )
        self.entry.async_on_unload(
            async_track_time_interval(
                self.hass, self._async_periodic_refresh, self._refresh_interval,
                name=f"powerview {self.client.host} refresh",
            )
        )

    async def _async_periodic_refresh(self, _now: Any) -> None:
        await self.async_refresh()

    # ----- notifications ----------------------------------------------------

    @callback
    def _notify(self, shade_id: int) -> None:
        async_dispatcher_send(self.hass, signal_shade_update(self.entry.entry_id, shade_id))

    @callback
    def _set_available(self, available: bool) -> None:
        if available != self.available:
            self.available = available
            if available:
                _LOGGER.info("PowerView gateway %s is reachable again", self.client.host)
            else:
                _LOGGER.warning("PowerView gateway %s is unreachable", self.client.host)
            async_dispatcher_send(self.hass, signal_hub_availability(self.entry.entry_id))

    # ----- state refresh ----------------------------------------------------

    async def async_refresh(self) -> None:
        """Fetch /home and apply positions to shades that are not moving."""
        try:
            raw = await self.client.get_home()
        except PowerViewError as err:
            _LOGGER.debug("Refresh of %s failed: %s", self.client.host, err)
            self._set_available(False)
            return
        self._set_available(True)
        for sid, info in parse_home(raw).shades.items():
            tracker = self.trackers.get(sid)
            if tracker is not None and tracker.snapshot(info.positions):
                self._notify(sid)

    # ----- SSE --------------------------------------------------------------

    async def _sse_loop(self) -> None:
        attempt = 0
        first = True
        while True:
            if not first:
                # Catch up on anything missed while the stream was down.
                await self.async_refresh()
            first = False
            try:
                async for event in self.client.iter_shade_events(SSE_IDLE_TIMEOUT):
                    if event.get("evt") == STREAM_OPENED:
                        attempt = 0
                        self.sse_connected = True
                        _LOGGER.debug("SSE stream open on %s", self.client.host)
                        continue
                    self._handle_event(event)
                _LOGGER.debug("SSE stream on %s closed by gateway", self.client.host)
            except PowerViewError as err:
                _LOGGER.debug("SSE stream on %s: %s", self.client.host, err)
            self.sse_connected = False
            delay = SSE_BACKOFF[min(attempt, len(SSE_BACKOFF) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    @callback
    def _handle_event(self, event: dict[str, Any]) -> None:
        raw_id = event.get("id")
        if not isinstance(raw_id, int) or (tracker := self.trackers.get(raw_id)) is None:
            return
        evt = event.get("evt")
        if evt == "motion-started":
            tracker.motion_started(event, time.monotonic())
            self._ensure_polling(raw_id)
        elif evt == "motion-stopped":
            tracker.motion_stopped(event)
        elif evt == "shade-online":
            tracker.online = True
        elif evt == "shade-offline":
            tracker.online = False
        else:
            # battery-alert is also sent for hard-wired shades right before motion;
            # it carries no position change, so it is ignored.
            _LOGGER.debug("Ignoring %s for shade %s", evt, raw_id)
            return
        self._notify(raw_id)

    # ----- polling while moving --------------------------------------------

    @callback
    def _ensure_polling(self, shade_id: int) -> None:
        task = self._poll_tasks.get(shade_id)
        if task is None or task.done():
            self._poll_tasks[shade_id] = self.entry.async_create_background_task(
                self.hass, self._poll_loop(shade_id), f"powerview poll shade {shade_id}"
            )

    async def _poll_loop(self, shade_id: int) -> None:
        tracker = self.trackers[shade_id]
        try:
            while tracker.moving:
                await asyncio.sleep(self._poll_interval)
                if not tracker.moving:
                    break
                try:
                    async with self._poll_sem:
                        raw = await self.client.get_shade(shade_id)
                except PowerViewError as err:
                    _LOGGER.debug("Poll of shade %s failed: %s", shade_id, err)
                    tracker.poll({}, time.monotonic())  # still lets timeouts end tracking
                else:
                    tracker.poll(raw.get("positions") or {}, time.monotonic())
                self._notify(shade_id)
        finally:
            if self._poll_tasks.get(shade_id) is asyncio.current_task():
                self._poll_tasks.pop(shade_id, None)

    # ----- commands ---------------------------------------------------------

    async def async_move(
        self, shade_id: int, *, primary: float | None = None, secondary: float | None = None
    ) -> None:
        """Move only the given rails; the shade keeps the others where they are."""
        try:
            await self.client.set_positions([shade_id], primary=primary, secondary=secondary)
        except PowerViewError as err:
            raise HomeAssistantError(f"PowerView gateway rejected the move: {err}") from err
        if self.trackers[shade_id].command(time.monotonic(), primary=primary, secondary=secondary):
            self._ensure_polling(shade_id)
        self._notify(shade_id)

    async def async_stop(self, shade_id: int) -> None:
        """Stop a shade."""
        try:
            await self.client.stop([shade_id])
        except PowerViewError as err:
            raise HomeAssistantError(f"PowerView gateway rejected the stop: {err}") from err
        tracker = self.trackers[shade_id]
        tracker.stop_requested(time.monotonic())
        if tracker.moving:
            self._ensure_polling(shade_id)
        self._notify(shade_id)

    async def async_activate_scene(self, scene_id: int) -> None:
        """Activate a gateway scene; resulting motion arrives via SSE."""
        try:
            await self.client.activate_scene(scene_id)
        except PowerViewError as err:
            raise HomeAssistantError(f"PowerView gateway rejected the scene: {err}") from err
