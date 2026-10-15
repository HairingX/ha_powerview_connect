"""Async HTTP + SSE client for a PowerView Gen 3 gateway (no Home Assistant imports).

Endpoints (Hunter Douglas Gen 3 OpenAPI spec, verified against firmware 3.2.59):
- GET  /home                                  full home document
- GET  /home/shades/{id}                      one shade (positions update live while moving)
- PUT  /home/shades/positions?ids=1,2         {"positions": {...}}; omitted rails are NOT changed
- PUT  /home/shades/stop?ids=1,2
- PUT  /home/scenes/{id}/activate
- GET  /home/shades/events?sse=true           server-sent events
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
import json
import logging
from typing import Any

import aiohttp

from .model import command_errors, parse_sse_line

_LOGGER = logging.getLogger(__name__)

# Pseudo-event yielded once when the SSE stream has been opened successfully.
STREAM_OPENED = "_stream_opened"


class PowerViewError(Exception):
    """Gateway returned an error."""


class PowerViewConnectionError(PowerViewError):
    """Gateway could not be reached."""


def _ids(shade_ids: Iterable[int]) -> str:
    ids = ",".join(str(int(i)) for i in shade_ids)
    if not ids:
        raise ValueError("At least one shade id is required")
    return ids


class PowerViewClient:
    """Minimal client for one Gen 3 gateway."""

    def __init__(self, session: aiohttp.ClientSession, host: str, request_timeout: float = 10.0) -> None:
        self._session = session
        self._host = host.strip().removeprefix("http://").rstrip("/")
        self._base = f"http://{self._host}"
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)

    @property
    def host(self) -> str:
        """Return the gateway host."""
        return self._host

    @property
    def base_url(self) -> str:
        """Return the base URL."""
        return self._base

    async def _request(self, method: str, path_and_query: str, json_body: Any = None) -> Any:
        url = f"{self._base}{path_and_query}"
        try:
            async with self._session.request(method, url, json=json_body, timeout=self._timeout) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise PowerViewError(f"{method} {path_and_query} -> HTTP {resp.status}: {text[:200]}")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PowerViewConnectionError(f"{method} {path_and_query} failed: {err!r}") from err
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError as err:
            raise PowerViewError(f"{method} {path_and_query} returned non-JSON: {text[:200]}") from err

    async def get_home(self) -> dict[str, Any]:
        """Return the /home document."""
        data = await self._request("GET", "/home")
        if not isinstance(data, dict):
            raise PowerViewError("/home did not return an object")
        return data

    async def get_shade(self, shade_id: int) -> dict[str, Any]:
        """Return one shade (served from the gateway; no forced BLE refresh)."""
        data = await self._request("GET", f"/home/shades/{int(shade_id)}")
        if not isinstance(data, dict):
            raise PowerViewError(f"/home/shades/{shade_id} did not return an object")
        return data

    async def set_positions(
        self,
        shade_ids: Iterable[int],
        *,
        primary: float | None = None,
        secondary: float | None = None,
        tilt: float | None = None,
        velocity: float | None = None,
    ) -> Any:
        """Move shades. Only the rails given are sent; the shade keeps the others."""
        positions = {
            key: round(min(1.0, max(0.0, float(value))), 4)
            for key, value in (("primary", primary), ("secondary", secondary), ("tilt", tilt), ("velocity", velocity))
            if value is not None
        }
        if not positions:
            raise ValueError("No position given")
        response = await self._request(
            "PUT", f"/home/shades/positions?ids={_ids(shade_ids)}", {"positions": positions}
        )
        if errors := command_errors(response):
            raise PowerViewError("; ".join(errors))
        return response

    async def stop(self, shade_ids: Iterable[int]) -> Any:
        """Stop shades."""
        response = await self._request("PUT", f"/home/shades/stop?ids={_ids(shade_ids)}")
        if errors := command_errors(response):
            raise PowerViewError("; ".join(errors))
        return response

    async def activate_scene(self, scene_id: int) -> Any:
        """Activate a scene stored on the gateway."""
        return await self._request("PUT", f"/home/scenes/{int(scene_id)}/activate")

    async def iter_shade_events(self, idle_timeout: float) -> AsyncIterator[dict[str, Any]]:
        """Yield shade events from the SSE stream until it closes or goes quiet.

        Raises PowerViewConnectionError when the stream cannot be opened, breaks,
        or receives no bytes for idle_timeout seconds; the caller reconnects.
        """
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=idle_timeout)
        url = f"{self._base}/home/shades/events?sse=true"
        try:
            async with self._session.get(url, timeout=timeout, headers={"Accept": "text/event-stream"}) as resp:
                if resp.status != 200:
                    raise PowerViewError(f"SSE stream returned HTTP {resp.status}")
                yield {"evt": STREAM_OPENED}
                async for raw_line in resp.content:
                    event = parse_sse_line(raw_line.decode("utf-8", "replace"))
                    if event is not None:
                        yield event
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PowerViewConnectionError(f"SSE stream ended: {err!r}") from err

