# Design

How the integration is built, and why. What the gateway does is the library's
(`powerview_connect`, its `docs/protocol.md`); this is what the integration makes of it.

## What was measured, and what follows from it

On a real gateway (firmware 3.2.59, 2026-10-15) with a hard-wired Duette top-down/bottom-up
shade (shade firmware 3.0.433):

| Observation | Design consequence |
|---|---|
| `PUT /home/shades/positions?ids=N` with `{"positions":{"primary":0.2}}` then `{"positions":{"secondary":0.5}}` back to back: **both rails move**. The answer's hex says "unchanged" (`0x8000`) for the rail not sent; the Gen 3 API description says such a rail "is not changed". | Every command sends only its own rail. Never both from a cache. |
| A crossing request (primary 0.5, then secondary 0.6): the **shade's firmware stops** the top rail at 0.5 (= 1 - primary). | No clamp in software. |
| The event stream `GET /home/shades/events?sse=true`: first `100 HELO`, then `data: {json}` lines. `motion-started` (with `targetPositions` and `etaInSeconds`, sent for every source: Home Assistant, the app, a voice assistant), `motion-stopped` (final `currentPositions`), `battery-alert` (`batteryLevel: 1`, right before every move, for hard-wired shades too - ignored); the API description also lists `shade-online` and `shade-offline`. No positions during a move. | The stream drives start and stop at once; nothing is polled while idle. |
| `motion-started` arrives right after the command; the motor starts 4-5 s later. | "No change yet" is not "stopped". |
| `etaInSeconds` against the real time from started to stopped: 5 → 9.6 s, 6 → 10.7, 9 → 16.6, 10 → 19.0-19.2, 19 → 41.8. | The estimate does not decide when a shade has arrived. |
| `GET /home/shades/{id}` (without `?refresh=true`) returns **live positions** while moving: 0.01 steps, about once a second, ramping up and down. The PowerView app evidently reads it too. | A moving shade is read about once a second, and only while it moves. |
| `motion-stopped` normally on time; once, for the largest two-rail move, perhaps 14-23 s late (not proven). | A move also ends when the target is reached and still for 1.5 s, on no change for 6 s, or at a timeout. |
| Both rails in one request: they start about 1 s apart and run together. | `powerview_connect.set_positions` sends both rails in one request. |
| `/home` lists every gateway (`aux: true` for auxiliary ones), rooms with their shades (`capabilities`, `type`, `powerType` 1 = hard-wired, `positions` 0-1), scenes (`_id`, `name`, members with `pos1`/`pos2` 0-10000). | The config flow reads `/home`, refuses auxiliary gateways, and takes the primary gateway's serial number as the unique id. |
| Positions run from 0.0, fully closed, to 1.0, fully open, per rail. On a top-down/bottom-up shade `primary` is the bottom rail and `secondary` the top rail. | The covers mean what the core integration's do, so cards keep working. |

## Why not the core integration

Home Assistant's `hunterdouglas_powerview` integration always sends both rails of a
top-down/bottom-up shade, filling the other from a cache that polling and its forced refresh
overwrite with stale gateway data, so back-to-back top and bottom commands revert each other
(home-assistant/core#122016). Its `cover.py` builds every top or bottom move from both
`primary` and `secondary`.

## The hub

One `PowerViewHub` per config entry holds the home as it was read at setup and a
`ShadeTracker` (from the library) per shade. It owns three things:

- **The event stream**, a background task that reopens it after it ends or breaks, with a
  growing wait. Each time it opens, the whole home is read, to catch up on what happened while
  it was closed. `motion-started` starts a shade's move and its reads; `motion-stopped` ends it;
  `shade-online` and `shade-offline` set the shade's availability.
- **Reads of moving shades**, one timer per shade, about once a second, at most three requests
  at a time. The tracker decides when a move has ended; a read that fails still lets its
  timeouts end it.
- **Commands**, sent for one rail, or both through the action. The tracker takes the command,
  so the cover shows opening or closing before the gateway's event arrives.

The tracker's clock is the hub's `clock`, `time.monotonic` unless a test sets another.

## Setup, availability and change

- Setup reads `/home`; a gateway that does not answer makes the entry retry later.
- The gateway is unavailable, and every entity with it, while reading the home or opening the
  stream fails; this is logged once when it happens and once when it ends.
- The whole home is read every 10 minutes (an option). Positions of shades not moving are
  taken; when the shades or scenes are not those set up, the entry reloads. Setup removes the
  devices of shades the home no longer has.

## Devices and entities

- The gateway is a device; each shade a device connected through it, in the area of its room.
- A shade's covers follow its capabilities, as the Gen 3 API describes them: two for
  top-down/bottom-up (*Top*, the top rail, and *Bottom*, the bottom rail), two for
  dual-overlapped (*Front*, the primary rail, and *Rear*, the secondary), one inverted for
  top-down, one for the primary rail otherwise. Vanes are a cover's tilt: the only rail's for a
  shade that tilts, the front's for a dual-overlapped one, and the whole cover of a tilt-only
  shade. Vertical shades are curtains. Only the top-down/bottom-up shade has been measured.
- The covers set `_attr_` values whenever the hub tells them their shade changed; nothing is
  polled by Home Assistant.
- Scenes belong to the gateway's device.
- A shade the gateway reports a signal strength for has a signal strength sensor, a diagnostic
  disabled by default. The hub keeps the value from each read of the home and of a moving shade.
  A shade whose `powerType` is not hard-wired (1) has a battery level and a low battery sensor; a
  hard-wired shade has neither, as it reports `batteryStatus` 3 too, and a shade that reports no
  power type is not taken to have a battery. The levels are the Gen 3 API's, not yet measured on
  a battery shade.

## Dependencies

`powerview_connect` holds everything about the gateway: the client, the parsing, the motion
tracker and a simulated gateway that the tests run the integration against. It uses Home
Assistant's shared aiohttp session.
