"""Dashboard read models: draft traces, the session index, and eval numbers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from firsthand.contracts import IssueDraft
from firsthand.storage import StateStore
from firsthand.web.intake import DraftRegistry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis

__all__ = ["DraftIndex", "DraftSummary", "load_drafts", "read_eval_report"]

_DRAFT_INDEX_KEY = "firsthand:web:drafts"

#: Draft states an operator can act on from the escalation queue.
REVIEWABLE_STATES = ("escalated",)


@dataclass(frozen=True)
class DraftSummary:
    """A dashboard row: the session id and the draft it currently holds."""

    session_id: str
    draft: IssueDraft

    @property
    def reviewable(self) -> bool:
        """Whether this draft is awaiting an approve/reject decision."""
        return self.draft.status in REVIEWABLE_STATES


class DraftIndex:
    """The set of sessions that have a draft — implements ``DraftRegistry``.

    The §3 ``StateStore`` has no scan operation by design; the intake layer
    maintains this side index so the dashboard can enumerate drafts without
    widening that contract.
    """

    def __init__(self, redis: Redis, *, key: str = _DRAFT_INDEX_KEY) -> None:
        self._redis = redis
        self._key = key

    async def register(self, session_id: str) -> None:
        await self._redis.sadd(self._key, session_id)

    async def session_ids(self) -> list[str]:
        members = await self._redis.smembers(self._key)
        return sorted(m.decode("utf-8") if isinstance(m, bytes) else m for m in members)


async def load_drafts(index: DraftRegistry, state: StateStore) -> list[DraftSummary]:
    """Resolve every indexed session to its current draft, skipping any that
    have since expired out of the ``StateStore``."""
    summaries: list[DraftSummary] = []
    for session_id in await index.session_ids():
        draft = await state.get(session_id)
        if draft is not None:
            summaries.append(DraftSummary(session_id=session_id, draft=draft))
    return summaries


def read_eval_report(path: str) -> dict[str, Any] | None:
    """Parse the eval report JSON if a path is configured and the file exists."""
    if not path:
        return None
    report_path = Path(path)
    if not report_path.is_file():
        return None
    parsed: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    return parsed
