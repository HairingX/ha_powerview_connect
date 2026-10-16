"""One gateway at runtime: its event stream, the shades it moves, and the commands sent to it."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from powerview_connect import (
    BatteryStatus,
    EventKind,
    Gateway,
    GatewayStatus,
    Home,
    PowerViewClient,
    PowerViewError,
    Rail,
    Shade,
    ShadeEvent,
    ShadeTracker,
)

from .const import (
    CONF_MOTION_POLL_INTERVAL,
    CONF_REFRESH_MINUTES,
    DEFAULT_MOTION_POLL_INTERVAL,
    DEFAULT_REFRESH_MINUTES,
    DOMAIN,
    GATEWAY_INTERVAL,
    MAX_CONCURRENT_POLLS,
    SSE_BACKOFF,
    SSE_IDLE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

type PowerViewConfigEntry = ConfigEntry[PowerViewHub]
type Listener = Callable[[], None]
type ListenKey = int | str | None
"""A shade's id, a gateway's serial number, or None for the hub's availability."""


def new_client(hass: HomeAssistant, host: str) -> PowerViewClient:
    """A client for the gateway at `host`, on Home Assistant's shared web session."""
    return PowerViewClient(async_get_clientsession(hass), host)


class PowerViewHub:
    """Everything known about one gateway's shades, kept current from its event stream.

    The stream says when a shade starts and stops moving; a shade is read only while it moves,
    and the whole home only now and then, in case an event was missed.
    """

    def __init__(
        self, hass: HomeAssistant, entry: PowerViewConfigEntry, client: PowerViewClient, home: Home
    ) -> None:
        """A hub for the gateway `client` reaches, whose home was just read."""
        self.hass = hass
        self.entry = entry
        self.client = client
        self.home = home
        self.unique_id: str = entry.unique_id or client.host
        self.gateway: Gateway | None = home.gateway_at(client.host) or home.primary_gateway
        self.signal_strengths: dict[int, int | None] = {
            shade_id: shade.signal_strength for shade_id, shade in home.shades.items()
        }
        """Each shade's signal strength in dBm, as last read."""
        self.batteries: dict[int, BatteryStatus | None] = {
            shade_id: shade.battery for shade_id, shade in home.shades.items()
        }
        """Each shade's battery status, as last read."""
        self.trackers: dict[int, ShadeTracker] = {
            shade_id: ShadeTracker(shade.positions) for shade_id, shade in home.shades.items()
        }
        self.gateway_clients: dict[str, PowerViewClient] = {}
        """A client of each gateway that can be asked of its state, by serial number."""
        for gateway in home.gateways:
            if gateway == self.gateway:
                self.gateway_clients[gateway.serial] = client
            elif gateway.ip:
                # Only ever asked of its state, so nothing can reach a shade through it.
                self.gateway_clients[gateway.serial] = PowerViewClient(
                    async_get_clientsession(hass), gateway.ip, read_only=True)
        self.gateway_states: dict[str, GatewayStatus | None] = dict.fromkeys(self.gateway_clients)
        """What each gateway last reported of itself; None while it does not answer."""
        self.gateway_device_id = ""
        """The primary gateway's device id, set when its device is registered."""
        self.gateway_device_ids: dict[str, str] = {}
        """Each gateway's device id by serial number, set when its device is registered."""
        self.unique_ids: set[str] = set()
        """The unique id of every entity the entry has, disabled ones included."""
        self.available = True
        self.stream_connected = False
        self.clock: Callable[[], float] = time.monotonic
        """The monotonic clock the shades' motion is timed by."""
        self._poll_interval = float(
            entry.options.get(CONF_MOTION_POLL_INTERVAL, DEFAULT_MOTION_POLL_INTERVAL)
        )
        self._refresh_interval = timedelta(
            minutes=int(entry.options.get(CONF_REFRESH_MINUTES, DEFAULT_REFRESH_MINUTES))
        )
        self._listeners: dict[ListenKey, list[Listener]] = {}
        self._polls: dict[int, CALLBACK_TYPE] = {}
        self._poll_slots = asyncio.Semaphore(MAX_CONCURRENT_POLLS)

    @callback
    def async_start(self) -> None:
        """Start listening to the event stream and refreshing the home now and then."""
        self.entry.async_create_background_task(
            self.hass, self._listen(), f"{DOMAIN} {self.entry.title} events"
        )
        self.entry.async_on_unload(
            async_track_time_interval(
                self.hass, self._refresh_now, self._refresh_interval,
                name=f"{DOMAIN} {self.entry.title} refresh",
            )
        )
        self.entry.async_on_unload(
            async_track_time_interval(
                self.hass, self._refresh_gateways_now, GATEWAY_INTERVAL,
                name=f"{DOMAIN} {self.entry.title} gateways",
            )
        )
        self.entry.async_on_unload(self._stop_polls)

    def via_device_id(self, shade_id: int) -> str:
        """The device id of the gateway that serves a shade, the primary one if none says so."""
        for gateway in self.home.gateways:
            if shade_id in gateway.shade_ids:
                return self.gateway_device_ids.get(gateway.serial, self.gateway_device_id)
        return self.gateway_device_id

    @callback
    def _stop_polls(self) -> None:
        for cancel in self._polls.values():
            cancel()
        self._polls.clear()

    # --------------------------------------------------------------- listeners

    @callback
    def async_listen(self, key: ListenKey, listener: Listener) -> CALLBACK_TYPE:
        """Call `listener` when the shade or gateway `key` names changes, or for None, when
        availability does."""
        listeners = self._listeners.setdefault(key, [])
        listeners.append(listener)

        @callback
        def remove() -> None:
            listeners.remove(listener)

        return remove

    @callback
    def _notify(self, key: ListenKey) -> None:
        for listener in list(self._listeners.get(key, [])):
            listener()

    @callback
    def _set_available(self, available: bool) -> None:
        if available == self.available:
            return
        self.available = available
        if available:
            _LOGGER.info("The PowerView gateway at %s answers again", self.client.host)
        else:
            _LOGGER.warning("The PowerView gateway at %s does not answer", self.client.host)
        self._notify(None)

    # ----------------------------------------------------------------- refresh

    async def _refresh_now(self, _: datetime) -> None:
        await self.async_refresh()

    async def async_refresh(self) -> None:
        """Read the whole home, and take the positions of the shades not moving.

        The entry reloads when the home's shades or scenes have changed.
        """
        try:
            home = await self.client.get_home()
        except PowerViewError as err:
            _LOGGER.debug("Reading the home at %s failed: %s", self.client.host, err)
            self._set_available(False)
            return
        self._set_available(True)
        if set(home.shades) != set(self.home.shades) or {
            scene.id for scene in home.scenes} != {scene.id for scene in self.home.scenes}:
            _LOGGER.info("The shades or scenes of %s have changed; reloading", self.entry.title)
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
            return
        for shade_id, shade in home.shades.items():
            moved = self.trackers[shade_id].snapshot(shade.positions)
            if self._take_reported(shade) or moved:
                self._notify(shade_id)

    @callback
    def _take_reported(self, shade: Shade) -> bool:
        """Keep a shade's signal strength and battery status; returns whether either changed."""
        changed = (self.signal_strengths[shade.id], self.batteries[shade.id]) != (
            shade.signal_strength, shade.battery)
        self.signal_strengths[shade.id] = shade.signal_strength
        self.batteries[shade.id] = shade.battery
        return changed

    # ---------------------------------------------------------------- gateways

    async def _refresh_gateways_now(self, _: datetime) -> None:
        await self.async_refresh_gateways()

    async def async_refresh_gateways(self) -> None:
        """Ask every gateway of the home of its own state, all at once."""
        serials = list(self.gateway_clients)
        found = await asyncio.gather(
            *(self.gateway_clients[serial].get_gateway() for serial in serials),
            return_exceptions=True,
        )
        for serial, status in zip(serials, found, strict=True):
            if isinstance(status, BaseException):
                if not isinstance(status, PowerViewError):
                    raise status
                _LOGGER.debug("Gateway %s does not answer: %s", serial, status)
                status = None
            if status != self.gateway_states[serial]:
                self.gateway_states[serial] = status
                self._notify(serial)

    # ------------------------------------------------------------ event stream

    async def _listen(self) -> None:
        """Follow the event stream for as long as the entry is loaded, reopening it when it ends."""
        attempt = 0
        while True:
            try:
                async with self.client.shade_events(SSE_IDLE_TIMEOUT) as events:
                    attempt = 0
                    self.stream_connected = True
                    _LOGGER.debug("Listening to the events of %s", self.client.host)
                    # What happened while the stream was closed is read once it is open.
                    await self.async_refresh()
                    async for event in events:
                        self._handle(event)
                _LOGGER.debug("The gateway at %s closed its event stream", self.client.host)
            except PowerViewError as err:
                _LOGGER.debug("The event stream of %s: %s", self.client.host, err)
                self._set_available(False)
            self.stream_connected = False
            await asyncio.sleep(SSE_BACKOFF[min(attempt, len(SSE_BACKOFF) - 1)])
            attempt += 1

    @callback
    def _handle(self, event: ShadeEvent) -> None:
        tracker = self.trackers.get(event.shade_id)
        if tracker is None:
            return
        match event.kind:
            case EventKind.MOTION_STARTED:
                tracker.motion_started(event, self.clock())
                self._poll_soon(event.shade_id)
            case EventKind.MOTION_STOPPED:
                tracker.motion_stopped(event)
            case EventKind.SHADE_ONLINE:
                tracker.online = True
            case EventKind.SHADE_OFFLINE:
                tracker.online = False
            case _:
                # A battery alert comes before every move, from hard-wired shades too.
                return
        self._notify(event.shade_id)

    # ------------------------------------------------------- polling while moving

    @callback
    def _poll_soon(self, shade_id: int) -> None:
        if shade_id in self._polls:
            return

        @callback
        def poll(_: datetime) -> None:
            del self._polls[shade_id]
            self.entry.async_create_task(
                self.hass, self._poll(shade_id), f"{DOMAIN} poll shade {shade_id}"
            )

        self._polls[shade_id] = async_call_later(self.hass, self._poll_interval, poll)

    async def _poll(self, shade_id: int) -> None:
        tracker = self.trackers[shade_id]
        try:
            async with self._poll_slots:
                shade = await self.client.get_shade(shade_id)
        except PowerViewError as err:
            _LOGGER.debug("Reading shade %s failed: %s", shade_id, err)
            # The timeouts still end a move the shade can no longer be asked about.
            moving = tracker.poll({}, self.clock())
        else:
            moving = tracker.poll(shade.positions, self.clock())
            self._take_reported(shade)
        if moving:
            self._poll_soon(shade_id)
        self._notify(shade_id)

    # ---------------------------------------------------------------- commands

    async def async_move(self, shade_id: int, targets: dict[Rail, float]) -> None:
        """Move only the rails in `targets`; the shade keeps the others where they are.

        Raises:
            HomeAssistantError: the gateway did not take the move.
        """
        try:
            await self.client.set_positions(
                [shade_id],
                primary=targets.get(Rail.PRIMARY),
                secondary=targets.get(Rail.SECONDARY),
                tilt=targets.get(Rail.TILT),
            )
        except PowerViewError as err:
            raise _command_failed(err) from err
        if self.trackers[shade_id].command(self.clock(), targets):
            self._poll_soon(shade_id)
        self._notify(shade_id)

    async def async_stop(self, shade_id: int) -> None:
        """Stop a shade where it is.

        Raises:
            HomeAssistantError: the gateway did not take the stop.
        """
        try:
            await self.client.stop([shade_id])
        except PowerViewError as err:
            raise _command_failed(err) from err
        tracker = self.trackers[shade_id]
        tracker.stop_requested(self.clock())
        if tracker.moving:
            self._poll_soon(shade_id)
        self._notify(shade_id)

    async def async_jog(self, shade_id: int) -> None:
        """Move a shade briefly back and forth, to show which one it is.

        Raises:
            HomeAssistantError: the gateway did not take the command.
        """
        try:
            await self.client.jog(shade_id)
        except PowerViewError as err:
            raise _command_failed(err) from err

    async def async_activate_scene(self, scene_id: int) -> None:
        """Activate a scene; the moves it starts arrive on the event stream.

        Raises:
            HomeAssistantError: the gateway did not take the scene.
        """
        try:
            await self.client.activate_scene(scene_id)
        except PowerViewError as err:
            raise _command_failed(err) from err


def _command_failed(err: PowerViewError) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_failed",
        translation_placeholders={"error": str(err)},
    )
