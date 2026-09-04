"""Phase 5 wiring: the real orchestrator behind the web intake seam."""

from __future__ import annotations

import types
from typing import Any, cast

from asgi_lifespan import LifespanManager
from tests.fakes import FakeRedis
from tests.phase2support import make_app, make_resources, make_settings
from tests.support import (
    InMemoryStateStore,
    InMemoryVectorStore,
    classification_entry,
    recorded_llm,
)

import firsthand.secrets as secrets
from firsthand.admin.connectors import ConnectorConfigStore
from firsthand.connectors.jira import JiraConnector, RecordedJiraTransport
from firsthand.contracts import ConnectorConfig, Conversation, ToolError
from firsthand.orchestrator import OrchestratorDeps, ToolRegistry
from firsthand.web.orchestrator import (
    LoopOrchestrator,
    StubOrchestrator,
    unconfigured_jira,
)
from firsthand.web.wiring import _build_orchestrator, _resolve_jira

_INCOMPLETE = "the pay button does nothing"


def _loop_deps(llm: Any) -> OrchestratorDeps:
    return OrchestratorDeps(
        llm=llm,
        vector_store=InMemoryVectorStore(),
        state_store=InMemoryStateStore(),
        tools=ToolRegistry(jira=JiraConnector(RecordedJiraTransport({}), browse_base_url="x")),
        project_key="FH",
    )


# --- LoopOrchestrator -------------------------------------------------------


async def test_advance_delegates_to_the_loop_and_maps_the_reply() -> None:
    llm = recorded_llm(
        completions=classification_entry(
            _INCOMPLETE,
            {"category": "bug", "extracted_fields": {"actual_behavior": "nothing"}, "summary": ""},
        )
    )
    deps = _loop_deps(llm)
    turn = await LoopOrchestrator(deps).advance(
        message=_INCOMPLETE,
        draft=None,
        conversation=Conversation(surface="web", session_id="s1"),
    )

    assert turn.done is False
    assert turn.reply  # a clarifying question came back
    assert turn.draft.status == "gathering_info"
    # the loop persisted the draft through the shared state store
    assert isinstance(deps.state_store, InMemoryStateStore)
    assert "s1" in deps.state_store.blobs


async def test_aclose_is_a_no_op_when_the_llm_has_no_client() -> None:
    await LoopOrchestrator(_loop_deps(recorded_llm())).aclose()  # RecordedLLM has no aclose()


async def test_aclose_releases_a_client_backed_llm() -> None:
    closed: list[bool] = []

    class _ClientLLM:
        async def aclose(self) -> None:
            closed.append(True)

    await LoopOrchestrator(_loop_deps(_ClientLLM())).aclose()
    assert closed == [True]


# --- unconfigured Jira ----------------------------------------------------


async def test_unconfigured_jira_fails_every_call_cleanly() -> None:
    jira = unconfigured_jira()
    search = await jira.search_jira("checkout slow")
    created = await jira.create_ticket(project_key="P", summary="s", description="d")
    assert isinstance(search, ToolError)
    assert isinstance(created, ToolError)
    assert "no Jira connector is configured" in search.error


# --- _resolve_jira ------------------------------------------------------------


def test_resolve_jira_without_a_config_is_the_no_op_connector() -> None:
    jira = _resolve_jira(None)
    assert isinstance(jira, JiraConnector)
    assert jira.issue_url("X-1") == "/browse/X-1"  # empty browse base = the stand-in


def test_resolve_jira_builds_a_real_connector_from_a_valid_config() -> None:
    config = ConnectorConfig(
        type="jira",
        base_url="https://acme.atlassian.net",
        credential=secrets.encrypt("bot@acme.com:token-123"),
        updated_by="admin",
    )
    jira = _resolve_jira(config)
    assert jira.issue_url("PAY-9") == "https://acme.atlassian.net/browse/PAY-9"


def test_resolve_jira_falls_back_when_the_stored_config_is_unusable() -> None:
    config = ConnectorConfig(
        type="jira",
        base_url="https://acme.atlassian.net",
        credential=secrets.encrypt("missing-the-colon"),
        updated_by="admin",
    )
    jira = _resolve_jira(config)
    assert jira.issue_url("PAY-9") == "/browse/PAY-9"  # degraded to the stand-in


# --- _build_orchestrator + startup wiring -----------------------------------


def _fake_app() -> Any:
    resources = make_resources(FakeRedis())
    return types.SimpleNamespace(state=types.SimpleNamespace(resources=resources))


def _empty_connectors() -> ConnectorConfigStore:
    return ConnectorConfigStore(cast(Any, FakeRedis()))


async def test_build_orchestrator_uses_the_stub_without_an_llm_key() -> None:
    orch = await _build_orchestrator(
        _fake_app(), make_settings(llm_api_key=""), _empty_connectors()
    )
    assert isinstance(orch, StubOrchestrator)


async def test_build_orchestrator_uses_the_real_loop_when_a_key_is_set() -> None:
    orch = await _build_orchestrator(
        _fake_app(), make_settings(llm_api_key="sk-test"), _empty_connectors()
    )
    assert isinstance(orch, LoopOrchestrator)
    await orch.aclose()  # release the real OpenAI client's connection pool


async def test_app_startup_selects_the_real_orchestrator_and_closes_it() -> None:
    app, _ = make_app(settings=make_settings(llm_api_key="sk-test"))
    async with LifespanManager(app):
        assert isinstance(app.state.orchestrator, LoopOrchestrator)
    # exiting the lifespan ran the shutdown closer without error
