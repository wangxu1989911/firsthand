"""Connector store, dashboard read models, and the admin write services."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from tests.fakes import FakeRedis
from tests.phase2support import SECRET

from firsthand.admin.connectors import CONNECTOR_TYPES, ConnectorConfigStore
from firsthand.admin.dashboard import (
    DraftIndex,
    DraftSummary,
    load_drafts,
    read_eval_report,
)
from firsthand.admin.service import review_draft, save_connector
from firsthand.contracts import ConnectorConfig, Conversation, DraftStatus, IssueDraft
from firsthand.secrets import decrypt
from firsthand.storage import RedisStateStore


def _draft(session_id: str, *, status: DraftStatus = "gathering_info") -> IssueDraft:
    draft = IssueDraft(
        conversation=Conversation(surface="web", session_id=session_id),
        raw_text="something",
    )
    draft.status = status
    return draft


# -------------------------------------------------------------- connector store


async def test_connector_store_round_trips_and_lists_in_order() -> None:
    store = ConnectorConfigStore(cast(Any, FakeRedis()))
    assert await store.get("jira") is None
    assert await store.list() == []

    await store.put(
        ConnectorConfig(type="docs", base_url="https://d", credential="c", updated_by="admin")
    )
    await store.put(
        ConnectorConfig(type="jira", base_url="https://j", credential="c", updated_by="admin")
    )
    assert CONNECTOR_TYPES == ("jira", "git", "docs")
    assert [c.type for c in await store.list()] == ["jira", "docs"]

    await store.delete("jira")
    assert [c.type for c in await store.list()] == ["docs"]


async def test_connector_store_decodes_bytes() -> None:
    store = ConnectorConfigStore(cast(Any, FakeRedis(raw_as_bytes=True)))
    await store.put(
        ConnectorConfig(type="git", base_url="https://g", credential="c", updated_by="admin")
    )
    got = await store.get("git")
    assert got is not None and got.base_url == "https://g"


# ----------------------------------------------------------------- draft index


async def test_draft_index_registers_and_lists_sorted() -> None:
    index = DraftIndex(cast(Any, FakeRedis()))
    assert await index.session_ids() == []
    await index.register("s-2")
    await index.register("s-1")
    await index.register("s-1")
    assert await index.session_ids() == ["s-1", "s-2"]


async def test_draft_index_decodes_bytes() -> None:
    index = DraftIndex(cast(Any, FakeRedis(raw_as_bytes=True)))
    await index.register("s-1")
    assert await index.session_ids() == ["s-1"]


async def test_load_drafts_skips_sessions_whose_draft_expired() -> None:
    redis = FakeRedis()
    index = DraftIndex(cast(Any, redis))
    state = RedisStateStore(cast(Any, redis), default_ttl_seconds=60)
    await index.register("s-live")
    await index.register("s-gone")
    await state.set("s-live", _draft("s-live"))

    summaries = await load_drafts(index, state)
    assert [s.session_id for s in summaries] == ["s-live"]
    assert isinstance(summaries[0], DraftSummary)


def test_draft_summary_reviewable_reflects_status() -> None:
    assert DraftSummary("s", _draft("s", status="escalated")).reviewable
    assert not DraftSummary("s", _draft("s", status="scored")).reviewable


# ---------------------------------------------------------------- eval report


def test_read_eval_report_handles_absence_and_presence(tmp_path: Path) -> None:
    assert read_eval_report("") is None
    assert read_eval_report(str(tmp_path / "missing.json")) is None

    report = tmp_path / "eval.json"
    report.write_text(json.dumps({"precision": 0.91, "recall": 0.84}), encoding="utf-8")
    assert read_eval_report(str(report)) == {"precision": 0.91, "recall": 0.84}


# ------------------------------------------------------------------- services


async def test_review_draft_approves_and_rejects() -> None:
    redis = FakeRedis()
    state = RedisStateStore(cast(Any, redis), default_ttl_seconds=60)
    await state.set("s-1", _draft("s-1", status="escalated"))
    await state.set("s-2", _draft("s-2", status="escalated"))

    approved = await review_draft(state, "s-1", "approve", reviewer="admin")
    assert approved.status == "filed"
    rejected = await review_draft(state, "s-2", "reject", reviewer="admin")
    assert rejected.status == "closed"
    assert (await state.get("s-1")).status == "filed"  # type: ignore[union-attr]


async def test_review_draft_rejects_unknown_or_unreviewable() -> None:
    redis = FakeRedis()
    state = RedisStateStore(cast(Any, redis), default_ttl_seconds=60)
    with pytest.raises(LookupError):
        await review_draft(state, "missing", "approve", reviewer="admin")

    await state.set("s-1", _draft("s-1", status="gathering_info"))
    with pytest.raises(ValueError, match="not awaiting review"):
        await review_draft(state, "s-1", "approve", reviewer="admin")


async def test_save_connector_encrypts_new_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRSTHAND_SECRET_KEY", SECRET)
    store = ConnectorConfigStore(cast(Any, FakeRedis()))

    created = await save_connector(
        store,
        connector_type="jira",
        base_url="https://j",
        credential="s3cr3t-token",
        enabled=True,
        updated_by="admin",
    )
    assert created.credential != "s3cr3t-token"
    assert decrypt(created.credential) == "s3cr3t-token"


async def test_save_connector_keeps_an_existing_secret_when_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRSTHAND_SECRET_KEY", SECRET)
    store = ConnectorConfigStore(cast(Any, FakeRedis()))
    first = await save_connector(
        store,
        connector_type="git",
        base_url="https://g",
        credential="keep-me",
        enabled=True,
        updated_by="admin",
    )
    updated = await save_connector(
        store,
        connector_type="git",
        base_url="https://g2",
        credential="",
        enabled=False,
        updated_by="admin",
    )
    assert updated.credential == first.credential
    assert updated.base_url == "https://g2"
    assert not updated.enabled


async def test_save_connector_stores_empty_when_new_and_blank() -> None:
    store = ConnectorConfigStore(cast(Any, FakeRedis()))
    created = await save_connector(
        store,
        connector_type="docs",
        base_url="https://d",
        credential="",
        enabled=True,
        updated_by="admin",
    )
    assert created.credential == ""
