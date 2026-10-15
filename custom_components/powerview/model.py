"""Pure data parsing for the PowerView Gen 3 gateway API (no Home Assistant imports).

Shapes are taken from a live Gen 3 gateway (firmware 3.2.59) and the Hunter Douglas
Gen 3 OpenAPI spec:
- GET /home                -> {"rooms": [{"_id", "name", "shades": [...]}], "scenes": [...], "gateways": [...]}
- GET /home/shades/{id}    -> one shade object
- SSE /home/shades/events  -> lines "data: {json}" with evt motion-started/motion-stopped/...
Positions are fractions 0.0-1.0 ("fully closed" -> "fully open") per rail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

RAILS: tuple[str, ...] = ("primary", "secondary", "tilt")


@dataclass(slots=True)
class GatewayInfo:
    """A Gen 3 gateway as listed in /home."""

    serial: str
    name: str
    ip: str | None
    model: str | None
    firmware: str | None
    is_primary: bool


@dataclass(slots=True)
class ShadeInfo:
    """Static information about a shade."""

    id: int
    name: str
    type: int | None
    capabilities: int
    power_type: int | None
    room_id: int | None
    room_name: str | None
    firmware: str | None
    ble_name: str | None
    serial: str | None
    positions: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class SceneInfo:
    """A scene stored on the gateway."""

    id: int
    name: str
    room_id: int | None


@dataclass(slots=True)
class HomeData:
    """Parsed /home response."""

    home_id: str | None
    gateways: list[GatewayInfo]
    shades: dict[int, ShadeInfo]
    scenes: list[SceneInfo]

    @property
    def primary_gateway(self) -> GatewayInfo | None:
        """Return the primary (non-aux) gateway, if listed."""
        return next((gw for gw in self.gateways if gw.is_primary), None)

    def gateway_for_host(self, host: str) -> GatewayInfo | None:
        """Return the gateway whose IP equals host."""
        return next((gw for gw in self.gateways if gw.ip == host), None)


def parse_positions(raw: Any) -> dict[str, float]:
    """Return the known rail positions from a positions object."""
    if not isinstance(raw, dict):
        return {}
    result: dict[str, float] = {}
    for rail in RAILS:
        value = raw.get(rail)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[rail] = min(1.0, max(0.0, float(value)))
    return result


def _firmware_str(raw: Any) -> str | None:
    if isinstance(raw, dict) and {"revision", "subRevision", "build"} <= raw.keys():
        return f"{raw['revision']}.{raw['subRevision']}.{raw['build']}"
    return None


def parse_shade(raw: dict[str, Any], room_name: str | None = None) -> ShadeInfo:
    """Parse one shade object (from /home rooms or /home/shades/{id})."""
    return ShadeInfo(
        id=int(raw["id"]),
        name=str(raw.get("ptName") or raw.get("bleName") or f"Shade {raw['id']}"),
        type=raw.get("type"),
        capabilities=int(raw.get("capabilities") or 0),
        power_type=raw.get("powerType"),
        room_id=raw.get("roomId"),
        room_name=room_name,
        firmware=_firmware_str(raw.get("firmware")),
        ble_name=raw.get("bleName"),
        serial=raw.get("serialNumber"),
        positions=parse_positions(raw.get("positions")),
    )


def parse_home(raw: dict[str, Any]) -> HomeData:
    """Parse the /home document."""
    gateways = [
        GatewayInfo(
            serial=str(gw.get("serial")),
            name=str(gw.get("name") or "PowerView Gateway"),
            ip=gw.get("ip"),
            model=gw.get("model"),
            firmware=gw.get("v"),
            is_primary=not gw.get("aux", False),
        )
        for gw in raw.get("gateways") or []
        if isinstance(gw, dict) and gw.get("serial")
    ]
    shades: dict[int, ShadeInfo] = {}
    for room in raw.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        for shade_raw in room.get("shades") or []:
            if isinstance(shade_raw, dict) and "id" in shade_raw:
                shade = parse_shade(shade_raw, room.get("name"))
                shades[shade.id] = shade
    scenes = [
        SceneInfo(id=int(sc["_id"]), name=str(sc.get("name") or f"Scene {sc['_id']}"), room_id=sc.get("room_Id"))
        for sc in raw.get("scenes") or []
        if isinstance(sc, dict) and "_id" in sc
    ]
    home = raw.get("home") if isinstance(raw.get("home"), dict) else {}
    return HomeData(
        home_id=raw.get("id") or home.get("key"),
        gateways=gateways,
        shades=shades,
        scenes=scenes,
    )


def parse_sse_line(line: str) -> dict[str, Any] | None:
    """Parse one line of the gateway's SSE stream.

    The stream starts with a status line ("100 HELO") and then sends
    "data: {json}" lines separated by blank lines. Anything that is not a
    JSON object on a data line is ignored.
    """
    line = line.strip()
    if not line.startswith("data:"):
        return None
    try:
        payload = json.loads(line[5:].strip())
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def command_errors(response: Any) -> list[str]:
    """Return error descriptions from a PUT /home/shades/positions or stop response.

    Observed success shape: {"err": 0, "responses": [{"bleName", "err": 0, "id", "hex"}], "wentViaHTTP": true}
    """
    errors: list[str] = []
    if not isinstance(response, dict):
        return errors
    if response.get("err") not in (None, 0):
        errors.append(f"gateway err={response.get('err')}")
    for item in response.get("responses") or []:
        if isinstance(item, dict) and item.get("err") not in (None, 0):
            errors.append(f"shade {item.get('id')} ({item.get('bleName')}) err={item.get('err')}")
    return errors
