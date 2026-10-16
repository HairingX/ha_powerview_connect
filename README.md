# PowerView Connect for Home Assistant

A Home Assistant integration for **Hunter Douglas / Luxaflex PowerView Gen 3** gateways, over
their local HTTP API and event stream on your own network - no cloud. Built on
[powerview_connect](https://github.com/HairingX/powerview_connect).

It is made for top-down/bottom-up shades, which Home Assistant's own PowerView integration moves
both rails of with every command, filling in the rail not asked for from a cached value - so two
commands sent close together, or a command right after one from the PowerView app, undo each
other. Here every command sends only its own rail, and the gateway leaves the other where it is.

## What it is for

- Move each rail of a top-down/bottom-up shade on its own, from a dashboard, a scene or an
  automation, without the other rail jumping back.
- See a shade start moving the moment it does, whatever moved it - Home Assistant, the PowerView
  app, a remote, a voice assistant - and follow its position while it moves.
- Activate the scenes stored on the gateway.

## Supported devices

- **PowerView Gen 3 gateways**, the primary gateway of a home. Run against a gateway with
  firmware 3.2.59.
- Through it, every shade of the home:

  | Shade (Gen 3 capabilities) | Covers |
  |---|---|
  | Top-down/bottom-up (7, such as Duette TDBU) | *Top* and *Bottom*, one per rail |
  | Bottom-up (0) | one, its rail |
  | Bottom-up with tilt, 90° or 180° (1, 2) | one, its rail, with the vanes as its tilt |
  | Vertical (3), with tilt (4) | one curtain, its rail, with the vanes as its tilt where it has them |
  | Tilt-only (5) | one, its vanes as its tilt |
  | Top-down (6) | one, its rail, 100 when lowered fully |
  | Dual-overlapped (8), with tilt (9, 10) | *Front* and *Rear*, one per fabric, the vanes as the front's tilt where it has them |
  | Any other | one, its primary rail |

  Run against a hard-wired Duette top-down/bottom-up shade (shade firmware 3.0.433). The other
  kinds follow Hunter Douglas's Gen 3 API description and have not been run against a real
  shade yet.
- Not supported: PowerView Gen 1 and Gen 2 hubs, which have another API; Home Assistant's own
  PowerView integration serves them.

## Requirements

- Home Assistant 2026.10.1 or newer.
- The primary gateway reachable from Home Assistant on TCP port 80. Nothing needs to reach Home
  Assistant: the event stream is a connection Home Assistant opens to the gateway. On a network
  split into VLANs, allow Home Assistant to the gateway's port 80 only.

## Installation

### With HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HairingX&repository=ha_powerview_connect&category=integration)

1. Select the button to open this repository in [HACS](https://hacs.xyz). Or add it yourself: in
   HACS, the three dots > **Custom repositories**, the repository
   `https://github.com/HairingX/ha_powerview_connect` and the type **Integration**.
2. Download **PowerView Connect**.
3. Restart Home Assistant.

HACS offers the releases; a pre-release only with **Show beta versions** switched on for the
repository.

### Manually

1. Download `powerview_connect.zip` from the
   [latest release](https://github.com/HairingX/ha_powerview_connect/releases/latest) - not the source
   code, whose manifest carries no version.
2. Unpack it into a new folder `custom_components/powerview_connect` in your Home Assistant
   configuration.
3. Restart Home Assistant.

## Setup

**Discovered:** a Gen 3 gateway announces itself on the network (mDNS, `_PowerView-G3._tcp`).
Home Assistant offers the primary gateway under Settings > Devices & services > Discovered;
confirm it there. Auxiliary gateways are not offered, as the primary gateway serves every shade
of the home. A home already added whose gateway turns up at a new address is moved there by
itself.

**By its address:**

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=powerview_connect)

Select the button, or go to Settings > Devices & services > Add integration >
**PowerView Connect**, and enter the **primary** gateway's IP address or host name.
An auxiliary gateway is refused, with the primary gateway's address.

The home is recognised by the primary gateway's **serial number**, not its address. When the
gateway gets a new address, **reconfigure** the entry (Settings > Devices & services >
PowerView Connect > the three dots > Reconfigure) and enter it; every device, entity
and its history stays. Reconfigure refuses another home's gateway.

**Options** (the entry's **Configure**):

| Option | Default | |
|---|---|---|
| Read a moving shade every | 1 s | How often a moving shade's position is read. A shade standing still is never read. |
| Read the whole home every | 10 min | How often every shade is read, in case an event was missed. |

## What you get

- **The gateway** - a device with its model, firmware, hardware version and serial number, and
  each scene stored on it as a **scene** entity, named as in the PowerView app.
- **Each auxiliary gateway** - a device of its own, connected through the primary gateway.
- **Each gateway**, the primary one too, has three diagnostic sensors, read once a minute:
  - **Connection** - on while the gateway answers. A gateway that stops answering shows here
    first, and so do the shades it serves.
  - **Internet** - on while the gateway reports it reaches the internet, which the PowerView app
    needs away from home.
  - **Network** - wired or Wi-Fi.
- **Each shade** - a device in the room the PowerView app puts it in, connected through the
  gateway that serves it, with its kind, type and firmware; and its **covers** (see Supported devices), each
  with:
  - its position, 0-100, and whether it is opening or closing;
  - the attribute `target_position`, where it is heading while it moves;
  - open, close, set position and stop. Stop stops the whole shade, as the gateway does.

  and a **Signal strength** sensor: how well the gateway hears the shade, in dBm, closer to 0
  being stronger. It is a diagnostic, disabled by default: enable it on the shade's device. It is
  read with the whole home, and while the shade moves.
- **Each shade** also has an **Identify** button, which jogs the shade briefly back and forth
  to show which one it is.
- **Each shade off mains power** - one whose power type is not hard-wired - also has a
  **Battery level** sensor (low, medium, high or plugged in, as the gateway reports it in steps)
  and a **Battery** sensor that is on while the level is low. A hard-wired shade has neither: it
  reports a battery level too, which means nothing for it.

A top-down/bottom-up shade's covers mean what they do in Home Assistant's own PowerView
integration:

| Cover | 0 | 100 |
|---|---|---|
| *Top* | top rail at the top | top rail fully down |
| *Bottom* | bottom rail fully down | bottom rail fully up |

The shade itself stops a rail where it meets the other one, so a command that would cross them
is safe.

**The action `powerview_connect.set_positions`** moves both rails of a top-down/bottom-up shade in one
command; give `top`, `bottom` or both, and a rail not given stays where it is. Target either of
the shade's two covers.

## How data is updated

The integration listens to the gateway's event stream, which says when a shade starts moving -
with where it is heading - and when it stops, whatever moved it. Nothing is read while nothing
moves:

- **A shade starts moving:** its covers show opening or closing at once. The motor starts some
  seconds after the command.
- **While it moves:** the shade, and only it, is read about once a second, so its position
  follows it.
- **It stops:** on the gateway's stop event; or when it has reached its target and stood still
  for 1.5 s, has not moved for 6 s, or has not started at all 25 s after the command - in case
  the stop event comes late or not at all.
- **Every minute**, each gateway is asked of its own state, auxiliary ones at their own
  address: only `GET /gateway`, which moves nothing.
- **Every 10 minutes**, the whole home is read, in case an event was missed. When the shades or
  scenes have changed, the entry reloads to add or remove them.
- When the stream breaks, it is reopened, and the whole home is read again.

## Examples

A card with buttons for a top-down/bottom-up shade's favourite positions:

```yaml
type: grid
columns: 3
cards:
  - type: button
    name: Privacy
    icon: mdi:roller-shade
    tap_action:
      action: perform-action
      perform_action: powerview_connect.set_positions
      target:
        entity_id: cover.living_room_kitchen_window_top   # either cover of the shade
      data:
        top: 0
        bottom: 50
  - type: button
    name: Light from above
    icon: mdi:roller-shade
    tap_action:
      action: perform-action
      perform_action: powerview_connect.set_positions
      target:
        entity_id: cover.living_room_kitchen_window_top
      data:
        top: 40
        bottom: 0
  - type: button
    name: Open
    icon: mdi:roller-shade-closed
    tap_action:
      action: perform-action
      perform_action: powerview_connect.set_positions
      target:
        entity_id: cover.living_room_kitchen_window_top
      data:
        top: 0
        bottom: 0
```

Lower the top rail at sunset, leaving the bottom rail where it is:

```yaml
automation:
  - alias: "Shades: top rail down at sunset"
    triggers:
      - trigger: sun
        event: sunset
    actions:
      - action: cover.set_cover_position
        target:
          entity_id: cover.living_room_kitchen_window_top
        data:
          position: 60
```

## Troubleshooting

- **"No PowerView Gen 3 gateway answers at this address."** Check the address, and that Home
  Assistant reaches the gateway on port 80: open `http://<gateway-ip>/home` from the Home
  Assistant host. A Gen 2 hub does not answer as a Gen 3 gateway.
- **"This is an auxiliary gateway."** Enter the primary gateway's address, which the message
  gives.
- **A shade shows the wrong position after a move.** The next read of the home, within
  10 minutes, corrects it; a debug log (below) shows the events the gateway sent.
- **The gateway got a new address.** Reconfigure the entry (see Setup).
- Anything else: download the diagnostics and a debug log (below) and open an issue.

## Diagnostics and debug logging

- **Download diagnostics** from the integration's menu: each shade's kind, type, firmware,
  positions and motion, whether the event stream is open, and what each gateway reports of
  itself. The gateways' addresses, serial numbers and Bluetooth names are left out.
- **Enable debug logging** from the same menu to log the integration and the library, every
  event the gateway sends included.

## Known limits

- Shades on auxiliary gateways are listed by the primary gateway and set up with it, but have
  not been followed live yet.
- Only the Duette top-down/bottom-up shade has been run against a real gateway. Tilting,
  vertical, dual-overlapped and battery-powered shades follow the Gen 3 API description: which
  fabric is front and which rear, and how far a 90° shade's vanes tilt, are as it describes them.
  If one behaves otherwise, please report it with the shade's `GET /home/shades/{id}`.
- Stop stops both rails of a top-down/bottom-up shade: the gateway stops a whole shade.
- No buttons for a shade's two favorite positions (the heart buttons of the app and the
  remote): the gateway's local API refuses that command; it takes only a jog.
- The battery levels are those the Gen 3 API describes; they have not been read from a battery
  shade yet. The gateway reports steps, not a percentage.
- The gateway's estimate of how long a move takes is about half the real time, so it is not
  used.
- Scenes are activated, not edited: create and change them in the PowerView app.
- Remotes are not shown: what the gateway lists for one has not been measured.
- What a gateway without internet reports has not been measured; the Internet sensor is on
  only while the gateway says `Connected`.

## Migrating from Home Assistant's PowerView integration

The two can run side by side; both are offered when a Gen 3 gateway is discovered.

1. Add this integration (see Setup).
2. Its covers mean the same as the core integration's (see What you get), so cards and
   automations keep working once they point at the new entities. Their entity IDs include the
   room, such as `cover.living_room_kitchen_window_top`.
3. To keep your entity IDs: delete the core integration's entry first, then rename each new
   entity (the entity's settings > Entity ID) to the ID the old one had. Its history does not
   come with it.
4. Delete the core integration's entry for the Gen 3 gateway, if you have not.

## Removing the integration

Settings > Devices & services > PowerView Connect > the three dots > Delete. Uninstall
it in HACS, or delete `custom_components/powerview_connect`, and restart Home Assistant.

A shade removed from the home in the PowerView app is removed by itself at the next read of the
home.

## Disclaimer

Provided "as is", without warranty of any kind. This project is unofficial and not affiliated
with or endorsed by Hunter Douglas. PowerView is a trademark of Hunter Douglas.
