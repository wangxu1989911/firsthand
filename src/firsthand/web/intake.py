"""The transport-agnostic intake seam (design doc §2, §9).

The clarification loop knows nothing about HTTP or Slack. A transport implements
:class:`IntakeAdapter` — the web chat does now, Slack (Phase 6) will do so
identically — and drives the shared loop through the :class:`Orchestrator`
protocol below.

**Phase 5 integration point.** Phase 1 builds the real orchestrator against the
same §3 contracts. When it lands, drop it in wherever a :class:`StubOrchestrator`
is constructed; nothing else in this package needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from firsthand.contracts import Conversation, IssueDraft


@dataclass(frozen=True)
class OrchestratorTurn:
    """One step of the loop: the updated draft, the reply to send, and whether
    the conversation is finished (filed, escalated, or capped)."""

    draft: IssueDraft
    reply: str
    done: bool


@runtime_checkable
class Orchestrator(Protocol):
    """The narrow surface the intake layer depends on.

    Takes the user's latest message plus the prior draft (``None`` on the first
    turn) and returns the updated draft and the next reply.
    """

    async def advance(
        self,
        *,
        message: str,
        draft: IssueDraft | None,
        conversation: Conversation,
    ) -> OrchestratorTurn: ...


@runtime_checkable
class DraftRegistry(Protocol):
    """Records which sessions have a draft, so the admin dashboard can list them.

    The §3 :class:`~firsthand.storage.StateStore` is deliberately a pure
    key-value contract with no enumeration; this side index is maintained by the
    intake layer instead of widening that contract.
    """

    async def register(self, session_id: str) -> None: ...

    async def session_ids(self) -> list[str]: ...


@dataclass(frozen=True)
class IntakeTurn:
    """What a transport gets back after feeding in one user message."""

    reply: str
    draft: IssueDraft
    done: bool


class IntakeAdapter(ABC):
    """A transport that feeds user messages into the clarification loop."""

    @abstractmethod
    async def handle(self, session_id: str, message: str) -> IntakeTurn:
        """Advance the conversation for ``session_id`` by one user message."""
        ...

    @abstractmethod
    async def draft_for(self, session_id: str) -> IssueDraft | None:
        """Return the draft accumulated so far for ``session_id``, if any."""
        ...
