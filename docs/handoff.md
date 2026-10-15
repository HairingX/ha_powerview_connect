# Handoff: state of the work and what is left

Written for the agent (or person) taking over this branch. Delete this file in the pull request
that completes the list below; its content then lives in `docs/design.md` and the README.

## Goal

A HACS-installable Home Assistant integration, domain `powerview`, for Hunter Douglas / Luxaflex
PowerView **Gen 3** gateways, built to the same standard as `HairingX/ha_wavin_sentio_connect`
(its CLAUDE.md, workflows, release process, tests, pyright strict, 100 % coverage, quality scale,
en + da translations, brand icons, diagnostics, dev container). Minimum Home Assistant: 2026.10.0.

It replaces the core `hunterdouglas_powerview` integration for Gen 3, whose top-down/bottom-up
(TDBU) handling is broken: it always sends both rails, filling the other one from a cache that
polling and its forced refresh overwrite with stale gateway data, so back-to-back top/bottom
commands revert each other (home-assistant/core#122016, still open; PR #156228 in 2025.12 fixed
only half). Code references: core `cover.py` `_get_shade_move` for `PowerViewShadeTDBUTop/Bottom`
always sets both `primary` and `secondary`; `_async_update_shade_data`/`async_update` write the
hub's state over the optimistic value; `_handle_coordinator_update` is gated only per entity.

## Measured on a real gateway (2026-10-15, firmware 3.2.59, Duette TDBU, shade firmware 3.0.433)

Everything below was observed, not assumed. Raw captures are in `tests/test_engine.py`.

| Observation | Design consequence |
|---|---|
| `PUT /home/shades/positions?ids=N` with `{"positions":{"primary":0.2}}` then `{"positions":{"secondary":0.5}}` back to back: **both rails move**. Response hex shows `0x8000` ("unchanged") for the omitted rail. Gen 3 OpenAPI spec: an omitted rail "is not changed". | Every command sends only its own rail. Never both from a cache. |
| Crossing request (primary 0.5, then secondary 0.6): the **shade firmware stops** secondary at 0.5 (= 1 − primary). | No software clamp needed for safety. |
| SSE `GET /home/shades/events?sse=true`: first line `100 HELO`, then `data: {json}` lines. Events: `motion-started` (with `targetPositions` incl. `etaInSeconds`, sent for every source: HA, app, Google), `motion-stopped` (final `currentPositions`), `battery-alert` (`batteryLevel: 1`, sent right before every motion even for hard-wired shades — ignore), spec also lists `shade-online`/`shade-offline`. No intermediate positions on the stream. | SSE drives start/stop instantly; no polling while idle. |
| `motion-started` arrives ~immediately after the command; the motor starts ~4–5 s later. | Do not treat "no change yet" as "stopped". |
| `etaInSeconds` vs real (`started`→`stopped`): 5→9.6 s, 6→10.7, 9→16.6, 10→19.0–19.2, 19→41.8. | ETA is not used to decide arrival. |
| `GET /home/shades/{id}` (no `?refresh=true`) returns **live intermediate positions** while moving: 0.01 steps, ~1 s, with ramp-up/down. The PowerView app evidently polls this too (jumps once per second, with ramps). | Poll ~1 s, only while a shade moves. |
| `motion-stopped` normally on time; once (the largest, two-rail move) possibly 14–23 s late (not proven). | End tracking also on: target reached and stable 1.5 s, stall 6 s, or timeout. |
| Two-rail move in one PUT: rails start ~1 s apart and run in parallel. | `set_positions` service sends both rails in one PUT. |
| `/home` lists all gateways (`aux: true` for auxiliaries), rooms with shades (`capabilities`, `type`, `powerType` 1 = hard-wired, `positions` 0–1), scenes (`_id`, `name`, members with `pos1/pos2` 0–10000). | Config flow reads `/home`, refuses auxiliary gateways, unique id = primary gateway serial. |
| Positions: per Gen 3 spec 0.0 = fully closed, 1.0 = fully open, per rail. TDBU: `primary` = bottom rail (HA bottom entity, 0 = down), `secondary` = top rail (HA top entity, 100 = fully down), same semantics as core. | Entity semantics identical to core, so cards keep working. |

Not verified yet: shades on **auxiliary** gateways (the primary's `/home` lists them, but live
polling and SSE for them were not tested); tilt / dual-overlapped / tilt-only types; battery shades.

## What exists on this branch

- Repository infrastructure copied from `ha_wavin_sentio_connect` and adapted: `.github/`
  (workflows, release scripts and their tests, release drafter, dependabot, issue template),
  `.vscode/`, `.devcontainer.json`, `scripts/`, `config/configuration.yaml`, `pyproject.toml`,
  `requirements-test.txt`, `hacs.json` (2026.10.0, zip release `powerview.zip`), LICENSE (AGPL-3.0).
  `test_build.py` has `LIBRARIES = ()` (no external library yet); the `library-released`
  workflow was not copied.
- `custom_components/powerview/` — a first, **never-run-under-Home-Assistant** draft:
  - Pure, HA-free protocol code, to move to the library repository: `model.py` (parsing `/home`, shades, scenes, SSE lines, command
    errors), `api.py` (aiohttp client: get_home, get_shade, set_positions single-rail, stop,
    activate_scene, iter_shade_events with a `STREAM_OPENED` pseudo-event and idle timeout),
    `motion.py` (`ShadeTracker` state machine: motion_started/stopped, command, poll,
    stop_requested, direction; settle 1.5 s, stall 6 s, start grace 25 s, timeout).
  - HA layer: `hub.py` (SSE loop with backoff and refresh on reconnect, poll-while-moving tasks,
    periodic refresh, commands, dispatcher signals), `entity.py`, `cover.py` (TDBU top/bottom,
    top-down inverted, others primary), `scene.py`, `config_flow.py` (user step + options flow
    with reload), `__init__.py` (entity service `powerview.set_positions` registered in
    `async_setup`), `const.py`, `services.yaml`, `icons.json`, `translations/en.json`.
- `tests/test_engine.py` — stdlib unittest of model + motion against captured data (passes).

## What is left (in order)

1. **Library repository `HairingX/powerview_connect`** (created by the owner; holds only a LICENSE).
   Build it like `HairingX/wavin_sentio_connect` (public; read its CLAUDE.md, pyproject.toml,
   src/ layout, py.typed, tests, release and PyPI workflows):
   - Move `model.py`, `api.py` and `motion.py` there, plus `testing.py`: a simulated gateway — an
     aiohttp web app serving `/home`, `/home/shades/{id}`, PUT positions/stop/scene activate and
     the SSE stream from per-subscriber queues, with test controls to emit events, set
     intermediate positions, finish motion, drop streams and go offline, behaving as the table
     above. No Home Assistant imports; aiohttp is its only runtime dependency.
   - **Names:** repository, distribution and import name are all `powerview_connect`, like
     `wavin_sentio_connect`. (The PyPI name `powerview` is taken by an unrelated Active Directory
     tool. The owner has reserved `powerview-connect` with a pending trusted publisher.)
   - pyright strict, 100 % coverage, tests of the client against `testing.py`, the captured data
     in `tests/test_engine.py` as fixtures, a live test reading a gateway given by an environment
     variable (read-only: GET /home and the SSE stream; it must never move a shade).
   - Release to PyPI with trusted publishing, exactly as `wavin_sentio_connect` does. The owner
     has registered a pending trusted publisher on PyPI for the project `powerview-connect`
     (PyPI normalises it to the same name as `powerview_connect`). It is bound to repository
     `HairingX/powerview_connect`, workflow file `.github/workflows/release.yml` and environment
     `pypi`, so keep exactly that file name and `environment: name: pypi` with
     `permissions: id-token: write` on the publish job. Ask the owner to confirm those three
     values on PyPI if the first publish is refused.
   - Then in this repository: depend on it in `manifest.json` `requirements` and
     `requirements-test.txt`, set `LIBRARIES` in `.github/scripts/test_build.py` (the repository and distribution
     name are both `powerview_connect`), copy the template's `library-released` workflow, and add the
     template's contract tests for the pin and for importing the library from its package.
   Until the library is released, keep developing both together with a branch of the same name
   in each repository, as the template's CI supports.
2. **Make it match the template's standard** (read the template's CLAUDE.md, it is the spec):
   - pyright strict 0 errors: use `_attr_` values set in an update method instead of overriding
     entity properties; `cast` JSON objects; no `type: ignore`.
   - Inject the monotonic clock in `hub.py` so tests control time.
   - Exceptions with `translation_domain`/`translation_key` (ConfigEntryNotReady
     `cannot_connect` with host placeholder; HomeAssistantError `command_failed`).
   - `translations/da.json` with exactly the keys of `en.json`; no `strings.json`.
   - `icons.json` for entity translation keys (top/bottom with open/closed state icons) and the
     service.
   - `diagnostics.py` (gateway firmware/model, shades with capabilities/type/positions/tracker
     state, sse_connected; redact host, serials, home id, ble names).
   - Brand icons in `custom_components/powerview/brand/` (Home Assistant serves `brand/` for
     custom integrations); take them from home-assistant/brands `core_integrations/hunterdouglas_powerview`
     and pin their sha256 in a contract test, like the template.
   - `quality_scale.yaml` listing every rule (the template's test has the list), reasons for
     exemptions.
   - Discovery: zeroconf `_PowerView-G3._tcp.local.` (abort for auxiliary gateways, update host
     of a known unique id = discovery-update-info), reconfigure flow, stale-devices (remove
     devices of shades no longer in `/home`), dynamic-devices (reload when the set of shades
     changes on refresh), `async_remove_config_entry_device`.
3. **Tests with pytest-homeassistant-custom-component** against the simulated gateway on
   127.0.0.1, 100 % coverage: config flow (user, aux refused, no shades, cannot connect,
   already configured, zeroconf, reconfigure, options), setup/unload, covers (state, opening/
   closing from SSE, live polling, single-rail payloads, set_positions, stop, firmware clamp),
   scenes, availability (gateway down/up, SSE reconnect + refresh), diagnostics, contract tests
   (translations parity, quality scale, hacs.json = tested HA version, icons, library pin,
   no real IPs). The integration's tests use the library's `testing.py` simulated gateway. A `live` test that only reads `/home` and the SSE stream of a gateway given by
   an environment variable, skipped otherwise. Delete `tests/test_engine.py` once its cases live
   in pytest.
4. `README.md` (template's sections: what it is for, supported devices, requirements, install
   with HACS and manually, setup, what you get, how data is updated, examples incl. a card calling
   `powerview.set_positions`, troubleshooting, diagnostics, known limits, migration from the core
   integration and renaming entity IDs, removal, disclaimer: unofficial, PowerView is a Hunter
   Douglas trademark) and `docs/design.md` (the table above, as design rationale).
5. Open the pull request, get Tests + Validate green, merge, run **Release** (release candidate).
6. Tell the owner the exact required-status-check names for the `main` ruleset.

## Owner's setup and preferences

- Home Assistant runs in Docker (moving to Proxmox later); no `configuration.yaml` edits —
  everything through the UI. Installs through HACS.
- Network: VLANs (core for servers, IoT); only needed ports opened. This integration needs only
  Home Assistant → primary gateway, TCP 80 (SSE is an outbound HTTP connection).
- Dashboard/UI labels in English; the owner writes Danish. Factual answers, unverified claims
  flagged.
- The `main` ruleset (pull requests only, owner bypass for merging) is created by the owner; the
  session proxy refused the rulesets API.
- No real IP addresses, hostnames, serial numbers or email addresses in tracked files.
