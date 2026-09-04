"""ChatService — the web transport's implementation of the intake seam.

It owns no conversation state itself (§8.3): the draft lives in the
``StateStore``, the transcript in the :class:`ConversationLog`, and the set of
active sessions in the :class:`DraftRegistry`. Any instance can serve any
follow-up.
"""

from __future__ import annotations

from firsthand.contracts import MAX_CLARIFICATION_ROUNDS, Conversation, IssueDraft, Surface
from firsthand.storage import StateStore
from firsthand.web.intake import DraftRegistry, IntakeAdapter, IntakeTurn, Orchestrator
from firsthand.web.log import ConversationLog, LogEntry

#: Used only if an orchestrator ever returns "not done" past the round cap —
#: the cap is load-bearing (§2), so the transport enforces it too.
_CAP_REACHED_REPLY = (
    "Thanks for the detail. I've reached the limit of what I can ask here, so "
    "I've handed this to a person to follow up with you."
)


class ChatService(IntakeAdapter):
    """Drives the clarification loop for one surface (``web`` by default)."""

    def __init__(
        self,
        state_store: StateStore,
        orchestrator: Orchestrator,
        log: ConversationLog,
        registry: DraftRegistry,
        *,
        surface: Surface = "web",
        state_ttl_seconds: int,
    ) -> None:
        if state_ttl_seconds <= 0:
            raise ValueError("state_ttl_seconds must be positive")
        self._state = state_store
        self._orchestrator = orchestrator
        self._log = log
        self._registry = registry
        self._surface = surface
        self._ttl = state_ttl_seconds

    async def handle(self, session_id: str, message: str) -> IntakeTurn:
        message = message.strip()
        if not message:
            raise ValueError("message must not be empty")

        prior = await self._state.get(session_id)
        conversation = Conversation(surface=self._surface, session_id=session_id)
        turn = await self._orchestrator.advance(
            message=message, draft=prior, conversation=conversation
        )

        draft, reply, done = turn.draft, turn.reply, turn.done
        if not done and draft.round >= MAX_CLARIFICATION_ROUNDS:
            reply, done = _CAP_REACHED_REPLY, True

        await self._state.set(session_id, draft, ttl_seconds=self._ttl)
        await self._log.append(session_id, "user", message)
        await self._log.append(session_id, "assistant", reply)
        await self._registry.register(session_id)
        return IntakeTurn(reply=reply, draft=draft, done=done)

    async def draft_for(self, session_id: str) -> IssueDraft | None:
        return await self._state.get(session_id)

    async def history(self, session_id: str) -> list[LogEntry]:
        """The transcript to render when a session's page is (re)loaded."""
        return await self._log.entries(session_id)
