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

## The integration is a link

Everything about PowerView - the event stream, reading moving shades, reading the home, each
gateway's state, which covers a shade has and how far each is open - is the library's
`PowerViewHub` and `covers`. The integration turns the hub's state into devices and entities,
and Home Assistant's actions into the hub's commands. It knows nothing of the gateway's
protocol.

- **Setup** makes the hub (`runtime.new_hub`, with the entry's options as its `Timing`) and
  loads the home; a gateway that does not answer makes the entry retry later. It registers
  each gateway's device, adds the platforms, and runs the hub's `run` as the entry's
  background task, which Home Assistant cancels when the entry unloads: nothing the hub does
  outlives the entry.
- **Entities** subscribe to their shade or gateway in `async_added_to_hass`, and to the
  connection, and set `_attr_` values from the state they are given; nothing is polled by
  Home Assistant. A shade entity is available while the hub is and the shade is online.
- **Commands** go to the hub; an error the gateway reports becomes a `HomeAssistantError`.
- **The config flow** loads a read-only hub (`runtime.new_probe`) at the address given, and reads
  from its home whether that is the primary gateway and which home it serves.
- **Only the library's public API** is used: the hub, its states and changes, the home's model,
  the covers and the errors.
- **The home changing**: a shade, scene or gateway added to it gets its device and entities
  without a reload; one removed, once the hub has missed it in two reads in a row, has its
  device or scene removed; a shade renamed, moved to another room or gateway, or with new
  firmware has its device updated. A gateway's hardware and firmware follow what it reports.
- **Stalled openings** are the hub's to retry, for the shades given a `StalledOpenRetry`. Each
  shade with a `retryable` cover has a configuration switch and two numbers, the delay and the
  threshold; they keep the shade's `RetrySettings` in the runtime, give the hub a
  `StalledOpenRetry` while the switch is on, and are restored after a restart by Home
  Assistant (`RestoreEntity`, `RestoreNumber`). A switch disabled or removed turns the retry off.
  The integration turns each `ShadeStalled` into the event `powerview_connect_shade_stalled`,
  naming the cover by the entity id the registry has for its unique id, so automations can tell
  the user.
- **Time**: the hub keeps time by `runtime.new_clock`, the event loop's own. The tests replace
  it with the library's `ManualClock`, so time passes only when a test advances it.

## Setup, availability and change

- The hub is unavailable, and every entity with it, while the primary gateway does not
  answer. A stream that is being reopened, or one that is silent because nothing moves, does
  not make it so. The library logs once when the gateway stops answering and once when it
  answers again.
- The whole home is read every 10 minutes (an option); a moving shade is read every second
  (an option).
- Setup removes the devices of shades and gateways the home no longer has, and the entities
  this version no longer makes.

## The log

The integration logs through the library's `powerview_connect` logger, which the manifest
names, so debug logging from the integration's menu covers it. It holds every event and every
request with its time, names shades and gateways by id and name, and leaves serial numbers and
Bluetooth names out.

## Devices and entities

- The primary gateway is a device, and each auxiliary gateway a device connected through it.
  Each shade is a device connected through the gateway whose `shd_Ids` lists it, the primary
  one when none does, in the area of its room.
- Each gateway that can be asked has three diagnostic entities: Connection, on while it answers
  and always available, as not answering is what it reports; Internet, from `internetState`;
  and Network, wired or Wi-Fi from the interface in use. The last two are unavailable while the
  gateway does not answer.
- A shade's covers follow its capabilities, as the Gen 3 API describes them: two for
  top-down/bottom-up (*Top*, the top rail, and *Bottom*, the bottom rail), two for
  dual-overlapped (*Front*, the primary rail, and *Rear*, the secondary), one inverted for
  top-down, one for the primary rail otherwise. Vanes are a cover's tilt: the only rail's for a
  shade that tilts, the front's for a dual-overlapped one, and the whole cover of a tilt-only
  shade. Vertical shades are curtains. Only the top-down/bottom-up shade has been measured.
- Scenes belong to the gateway's device.
- Each shade has an Identify button, a jog. The gateway takes no other motion: a move to either
  of a shade's two favorite positions is refused with HTTP 400, so there are no buttons for them.
- A shade the gateway reports a signal strength for has a signal strength sensor, a diagnostic
  disabled by default. The hub keeps the value from each read of the home and of a moving shade.
  A shade whose `powerType` is not hard-wired (1) has a battery level and a low battery sensor; a
  hard-wired shade has neither, as it reports `batteryStatus` 3 too, and a shade that reports no
  power type is not taken to have a battery. The levels are the Gen 3 API's, not yet measured on
  a battery shade.

## Dependencies

`powerview_connect` holds everything about the gateway: the hub, the covers, the client, the
parsing, the motion tracker, and the simulated gateway and manual clock the tests run the
integration against. It uses Home Assistant's shared aiohttp session.
