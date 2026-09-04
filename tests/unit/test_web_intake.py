"""Redaction, the stub orchestrator, and the ChatService intake seam."""

from __future__ import annotations

from typing import Any, cast

import pytest
from tests.fakes import FakeRedis

from firsthand.contracts import (
    MAX_CLARIFICATION_ROUNDS,
    Conversation,
    IssueDraft,
    Surface,
)
from firsthand.storage import RedisStateStore
from firsthand.web.intake import IntakeTurn, Orchestrator, OrchestratorTurn
from firsthand.web.log import ConversationLog, LogEntry
from firsthand.web.orchestrator import StubOrchestrator
from firsthand.web.redaction import redact
from firsthand.web.service import ChatService

WEB: Surface = "web"


def _conversation(session_id: str = "s-1") -> Conversation:
    return Conversation(surface=WEB, session_id=session_id)


# ----------------------------------------------------------------- redaction


def test_redaction_masks_emails_and_phone_numbers() -> None:
    assert redact("mail me at jane@example.com") == "mail me at <EMAIL>"
    assert "<PHONE>" in redact("call +1 (415) 555-2671 today")


def test_redaction_leaves_ordinary_text_untouched() -> None:
    assert redact("the export button is missing") == "the export button is missing"


# ------------------------------------------------------------ stub orchestrator


async def _run(orch: Orchestrator, messages: list[str], conversation: Conversation) -> IssueDraft:
    draft: IssueDraft | None = None
    for message in messages:
        turn = await orch.advance(message=message, draft=draft, conversation=conversation)
        draft = turn.draft
    assert draft is not None
    return draft


async def test_a_bug_is_classified_and_asked_about() -> None:
    orch = StubOrchestrator()
    turn = await orch.advance(
        message="the export is broken", draft=None, conversation=_conversation()
    )
    assert turn.draft.category == "bug"
    assert turn.draft.required_fields == ["steps_to_reproduce", "affected_version"]
    assert turn.draft.round == 1
    assert not turn.done
    assert turn.reply


async def test_a_question_is_classified() -> None:
    turn = await StubOrchestrator().advance(
        message="how do i export my data?", draft=None, conversation=_conversation()
    )
    assert turn.draft.category == "question"


async def test_anything_else_is_a_feature() -> None:
    turn = await StubOrchestrator().advance(
        message="please add a dark mode", draft=None, conversation=_conversation()
    )
    assert turn.draft.category == "feature"


async def test_cooperative_answers_reach_auto_file() -> None:
    orch = StubOrchestrator()
    draft = await _run(
        orch,
        ["dark mode please", "night shifts hurt my eyes", "a toggle in settings"],
        _conversation(),
    )
    assert draft.status == "scored"
    assert draft.routing is not None and draft.routing.decision == "auto_file"
    assert draft.score is not None


async def test_an_urgent_request_escalates_on_completion() -> None:
    orch = StubOrchestrator()
    turn = await orch.advance(
        message="URGENT: how do i recover a deleted board?",
        draft=None,
        conversation=_conversation(),
    )
    final = await orch.advance(
        message="i deleted it this morning", draft=turn.draft, conversation=_conversation()
    )
    assert final.done
    assert final.draft.status == "escalated"
    assert final.draft.routing is not None and final.draft.routing.decision == "escalate"
    assert final.draft.score is not None and final.draft.score.urgency == "high"


async def test_the_round_cap_forces_a_handoff() -> None:
    orch = StubOrchestrator()
    conversation = _conversation()
    draft: IssueDraft | None = None
    for message in ["it is broken", "  ", "  ", "  "]:
        turn = await orch.advance(message=message, draft=draft, conversation=conversation)
        draft = turn.draft
    assert draft is not None
    assert draft.round == MAX_CLARIFICATION_ROUNDS
    assert turn.done
    assert draft.status == "escalated"
    assert draft.missing_fields == ["steps_to_reproduce", "affected_version"]


async def test_messages_after_completion_are_absorbed_without_error() -> None:
    orch = StubOrchestrator()
    draft = await _run(
        orch, ["dark mode", "eye strain", "settings toggle", "thanks!"], _conversation()
    )
    assert draft.status == "scored"


# ------------------------------------------------------------------- ChatService


def _service(redis: FakeRedis, orchestrator: Orchestrator | None = None) -> ChatService:
    return ChatService(
        RedisStateStore(cast(Any, redis), default_ttl_seconds=3600),
        orchestrator or StubOrchestrator(),
        ConversationLog(cast(Any, redis), ttl_seconds=3600),
        _RecordingRegistry(),
        state_ttl_seconds=3600,
    )


class _RecordingRegistry:
    def __init__(self) -> None:
        self.registered: list[str] = []

    async def register(self, session_id: str) -> None:
        self.registered.append(session_id)

    async def session_ids(self) -> list[str]:
        return sorted(set(self.registered))


class _RunawayOrchestrator:
    """Never says it's done, and pushes the round past the cap."""

    async def advance(
        self, *, message: str, draft: IssueDraft | None, conversation: Conversation
    ) -> OrchestratorTurn:
        base = draft or IssueDraft(conversation=conversation, raw_text=message)
        base.round = MAX_CLARIFICATION_ROUNDS + 1
        return OrchestratorTurn(draft=base, reply="and another thing?", done=False)


async def test_chat_service_rejects_an_empty_message() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        await _service(FakeRedis()).handle("s-1", "   ")


async def test_chat_service_persists_state_and_transcript() -> None:
    redis = FakeRedis()
    service = _service(redis)

    first = await service.handle("s-1", "the dashboard is broken")
    assert isinstance(first, IntakeTurn)
    assert not first.done

    stored = await service.draft_for("s-1")
    assert stored is not None and stored.category == "bug"

    history = await service.history("s-1")
    assert [entry.role for entry in history] == ["user", "assistant"]
    assert history[0].text == "the dashboard is broken"


async def test_chat_service_enforces_the_cap_even_if_the_orchestrator_will_not() -> None:
    redis = FakeRedis()
    service = _service(redis, _RunawayOrchestrator())
    turn = await service.handle("s-1", "hello")
    assert turn.done
    assert "person" in turn.reply.lower()


async def test_conversation_log_appends_expires_and_reads_back() -> None:
    redis = FakeRedis()
    log = ConversationLog(cast(Any, redis), ttl_seconds=120)
    assert await log.entries("s-1") == []

    await log.append("s-1", "user", "hello")
    await log.append("s-1", "assistant", "hi there")
    assert await log.entries("s-1") == [
        LogEntry("user", "hello"),
        LogEntry("assistant", "hi there"),
    ]
    assert redis.expirations["firsthand:web:log:s-1"] == 120


async def test_conversation_log_decodes_a_bytes_reply() -> None:
    redis = FakeRedis(raw_as_bytes=True)
    log = ConversationLog(cast(Any, redis), ttl_seconds=120)
    await log.append("s-1", "user", "hello")
    assert await log.entries("s-1") == [LogEntry("user", "hello")]


def test_conversation_log_rejects_a_nonpositive_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_seconds must be positive"):
        ConversationLog(cast(Any, FakeRedis()), ttl_seconds=0)


async def test_chat_service_rejects_a_nonpositive_ttl() -> None:
    with pytest.raises(ValueError, match="state_ttl_seconds must be positive"):
        ChatService(
            cast(Any, None),
            StubOrchestrator(),
            cast(Any, None),
            _RecordingRegistry(),
            state_ttl_seconds=0,
        )
