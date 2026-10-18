"""What the entities that retry a stalled opening share: the covers they are for."""

from __future__ import annotations

from collections.abc import Iterable

from powerview_connect import CoverRole

from .entity import Members, cover_unique_id
from .runtime import PowerViewRuntime


def retryable(
    runtime: PowerViewRuntime, members: Members
) -> Iterable[tuple[int, CoverRole, str]]:
    """Each cover of the shades among `members` whose opening can be retried: its shade's id,
    its role and its unique id."""
    for shade_id in sorted(members.shades):
        for cover in runtime.hub.shade(shade_id).covers:
            if cover.retryable:
                yield shade_id, cover.role, cover_unique_id(runtime, shade_id, cover.role)
