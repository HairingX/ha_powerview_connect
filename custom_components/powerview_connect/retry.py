"""What the entities that retry a stalled opening share: the shades they are for."""

from __future__ import annotations

from collections.abc import Iterable

from .entity import Members, cover_unique_id
from .runtime import PowerViewRuntime


def retryable(runtime: PowerViewRuntime, members: Members) -> Iterable[tuple[int, str]]:
    """Each shade among `members` whose opening can be retried, with its cover's unique id."""
    for shade_id in sorted(members.shades):
        for cover in runtime.hub.shade(shade_id).covers:
            if cover.retryable:
                yield shade_id, cover_unique_id(runtime, shade_id, cover.role)
