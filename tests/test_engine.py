"""Tests for the pure parts of custom_components/powerview using data captured
from a real Gen 3 gateway (192.0.2.32, firmware 3.2.59) on 2026-10-15.

Run: python -m unittest discover -s tests  (from the build directory)
"""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "powerview"

# Load model.py and motion.py without importing the HA package __init__.
pkg = types.ModuleType("pvpkg")
pkg.__path__ = [str(ROOT)]
sys.modules["pvpkg"] = pkg
for name in ("model", "motion"):
    spec = importlib.util.spec_from_file_location(f"pvpkg.{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"pvpkg.{name}"] = mod
    spec.loader.exec_module(mod)

from pvpkg.model import command_errors, parse_home, parse_sse_line  # noqa: E402
from pvpkg.motion import ShadeTracker  # noqa: E402

# --- Captured SSE stream (verbatim lines from the gateway) -----------------
SSE_CAPTURE = """100 HELO

data: {"evt":"battery-alert","isoDate":"2026-10-15T13:54:47.917Z","bleName":"DU1:0154","id":154,"currentPositions":{"primary":0,"secondary":0.71,"tilt":0},"batteryLevel":1}

data: {"evt":"motion-started","isoDate":"2026-10-15T13:54:48.474Z","bleName":"DU1:0154","id":154,"currentPositions":{"primary":0,"secondary":0.71,"tilt":0},"targetPositions":{"primary":0,"secondary":0.5,"tilt":0,"etaInSeconds":10}}

data: {"evt":"motion-stopped","isoDate":"2026-10-15T13:55:07.385Z","bleName":"DU1:0154","id":154,"currentPositions":{"primary":0,"secondary":0.5,"tilt":0}}
"""

# --- Captured poll series: GET /home/shades/154 every ~1 s during primary 0.18 -> 0
POLL_SERIES = [
    (0.4, 0.18), (1.7, 0.18), (2.8, 0.18), (3.7, 0.18), (4.9, 0.17), (5.8, 0.16), (7.0, 0.15),
    (8.1, 0.13), (9.0, 0.12), (10.0, 0.11), (11.9, 0.09), (13.7, 0.07), (14.7, 0.04), (15.8, 0.03),
    (17.3, 0.02), (18.3, 0.01), (19.5, 0.0), (20.5, 0.0), (21.4, 0.0), (22.7, 0.0), (23.7, 0.0), (24.6, 0.0),
]

# --- Trimmed /home document (structure verbatim, two shades, one scene) ----
HOME = {
    "id": "home-0001",
    "rooms": [
        {"_id": 65, "name": "Main Room", "shades": [
            {"id": 154, "type": 8, "ptName": "Kitchen Middle Curtain", "capabilities": 7, "powerType": 1,
             "batteryStatus": 3, "roomId": 65, "firmware": {"revision": 3, "subRevision": 0, "build": 433},
             "positions": {"primary": 0, "secondary": 0.71, "tilt": 0, "velocity": 0},
             "bleName": "DU1:0154", "serialNumber": "0000000000000154"},
            {"id": 271, "type": 6, "ptName": "Living Room East Curtain", "capabilities": 0, "powerType": 1,
             "roomId": 65, "firmware": {"revision": 3, "subRevision": 0, "build": 391},
             "positions": {"primary": 0, "secondary": 0, "tilt": 1, "velocity": 0}, "bleName": "DUT:0271"},
        ]},
    ],
    "scenes": [{"_id": 216, "name": "Kitchen Dining", "room_Id": 65,
                "members": [{"shd_Id": 154, "pos": {"pos1": 0, "pos2": 4580}}]}],
    "gateways": [
        {"v": "3.2.59", "serial": "gateway-primary-01", "model": "Pro", "name": "Main Room Gateway",
         "ip": "192.0.2.32", "aux": False},
        {"v": "3.2.59", "serial": "gateway-aux-02", "model": "Pro", "name": "Bedroom Gateway",
         "ip": "192.0.2.31", "aux": True},
    ],
}


class ModelTests(unittest.TestCase):
    def test_sse_parsing(self):
        events = [e for e in map(parse_sse_line, SSE_CAPTURE.splitlines()) if e]
        self.assertEqual([e["evt"] for e in events], ["battery-alert", "motion-started", "motion-stopped"])
        self.assertEqual(events[1]["targetPositions"]["secondary"], 0.5)
        self.assertIsNone(parse_sse_line("100 HELO"))
        self.assertIsNone(parse_sse_line("data: not json"))

    def test_parse_home(self):
        home = parse_home(HOME)
        self.assertEqual(home.primary_gateway.serial, "gateway-primary-01")
        self.assertTrue(home.gateway_for_host("192.0.2.32").is_primary)
        self.assertFalse(home.gateway_for_host("192.0.2.31").is_primary)
        km = home.shades[154]
        self.assertEqual((km.name, km.capabilities, km.room_name, km.firmware), ("Kitchen Middle Curtain", 7, "Main Room", "3.0.433"))
        self.assertEqual(km.positions, {"primary": 0.0, "secondary": 0.71, "tilt": 0.0})
        self.assertEqual([(s.id, s.name) for s in home.scenes], [(216, "Kitchen Dining")])

    def test_command_errors(self):
        ok = {"err": 0, "responses": [{"bleName": "DU1:0154", "err": 0, "id": 154, "hex": "e701"}], "wentViaHTTP": True}
        self.assertEqual(command_errors(ok), [])
        bad = {"err": 0, "responses": [{"bleName": "DU1:0154", "err": 7, "id": 154}]}
        self.assertEqual(len(command_errors(bad)), 1)


class TrackerTests(unittest.TestCase):
    def test_sse_only_cycle(self):
        t = ShadeTracker({"primary": 0, "secondary": 0.71, "tilt": 0})
        events = [e for e in map(parse_sse_line, SSE_CAPTURE.splitlines()) if e]
        t.motion_started(events[1], now=0.0)
        self.assertTrue(t.moving)
        self.assertEqual(t.direction("secondary"), -1)  # 0.71 -> 0.5 is closing
        self.assertEqual(t.direction("primary"), 0)
        self.assertEqual(t.eta, 10)
        t.motion_stopped(events[2])
        self.assertFalse(t.moving)
        self.assertEqual(t.current["secondary"], 0.5)

    def test_poll_series_finishes_when_target_reached(self):
        t = ShadeTracker({"primary": 0.18, "secondary": 0.5, "tilt": 0})
        t.motion_started({"currentPositions": {"primary": 0.18, "secondary": 0.5, "tilt": 0},
                          "targetPositions": {"primary": 0, "secondary": 0.5, "tilt": 0, "etaInSeconds": 9}}, now=0.0)
        finished_at = None
        for ts, primary in POLL_SERIES:
            keep = t.poll({"primary": primary, "secondary": 0.5, "tilt": 0}, now=ts)
            if ts < 19.5:
                self.assertTrue(keep, f"stopped too early at {ts}")
                self.assertEqual(t.direction("primary"), -1)
            if not keep:
                finished_at = ts
                break
        # Reached 0 at 19.5 s; finished after the 1.5 s settle -> first poll >= 21.0 s
        self.assertEqual(finished_at, 21.4)
        self.assertEqual(t.current["primary"], 0.0)

    def test_startup_delay_does_not_end_tracking(self):
        t = ShadeTracker({"primary": 0.18, "secondary": 0.5, "tilt": 0})
        self.assertTrue(t.command(0.0, primary=0.0))
        for ts in (1.0, 2.0, 3.0, 4.0):  # motor not started yet (~4-5 s observed)
            self.assertTrue(t.poll({"primary": 0.18, "secondary": 0.5}, now=ts))

    def test_clamped_target_ends_by_stall(self):
        # Overlap test: primary 0.5, secondary asked 0.6, firmware stops it at 0.5.
        t = ShadeTracker({"primary": 0.5, "secondary": 0.0, "tilt": 0})
        t.command(0.0, secondary=0.6)
        t.poll({"primary": 0.5, "secondary": 0.2}, now=6.0)
        t.poll({"primary": 0.5, "secondary": 0.5}, now=12.0)
        self.assertTrue(t.poll({"primary": 0.5, "secondary": 0.5}, now=15.0))
        self.assertFalse(t.poll({"primary": 0.5, "secondary": 0.5}, now=18.5))  # 6.5 s quiet
        self.assertEqual(t.current["secondary"], 0.5)

    def test_noop_command(self):
        t = ShadeTracker({"primary": 0.2, "secondary": 0.5})
        self.assertFalse(t.command(0.0, primary=0.2))
        self.assertFalse(t.moving)

    def test_second_rail_command_during_motion_keeps_first_target(self):
        t = ShadeTracker({"primary": 0.0, "secondary": 0.71})
        t.command(0.0, primary=0.2)
        t.command(0.5, secondary=0.5)
        self.assertEqual((t.target["primary"], t.target["secondary"]), (0.2, 0.5))
        self.assertEqual((t.direction("primary"), t.direction("secondary")), (1, -1))

    def test_late_motion_stopped_is_harmless(self):
        t = ShadeTracker({"primary": 0.0, "secondary": 0.71})
        t.command(0.0, secondary=0.5)
        t.poll({"secondary": 0.6}, now=6.0)
        t.poll({"secondary": 0.5}, now=12.0)
        self.assertFalse(t.poll({"secondary": 0.5}, now=14.0))
        t.motion_stopped({"currentPositions": {"primary": 0.0, "secondary": 0.5, "tilt": 0}})
        self.assertFalse(t.moving)
        self.assertEqual(t.current["secondary"], 0.5)

    def test_snapshot_ignored_while_moving(self):
        t = ShadeTracker({"primary": 0.0})
        t.command(0.0, primary=0.5)
        self.assertFalse(t.snapshot({"primary": 0.0}))
        t.poll({"primary": 0.2}, now=5.0)
        self.assertEqual(t.current["primary"], 0.2)


if __name__ == "__main__":
    unittest.main()
