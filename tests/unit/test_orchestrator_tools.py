"""ToolRegistry is the one place the §7 tool-call cap is enforced."""

from __future__ import annotations

import pytest

from firsthand.connectors.jira import JiraConnector, RecordedJiraTransport, search_response
from firsthand.contracts import MAX_TOOL_CALLS, ToolSuccess
from firsthand.orchestrator.tools import ToolBudgetError, ToolRegistry


def _registry() -> ToolRegistry:
    transport = RecordedJiraTransport(
        {
            "GET /rest/api/3/search": [
                search_response(("PAY-1", "s", "Open")) for _ in range(MAX_TOOL_CALLS + 2)
            ],
            "POST /rest/api/3/issue": [{"key": "PAY-9"} for _ in range(MAX_TOOL_CALLS + 2)],
            "POST /rest/api/3/issueLink": [{} for _ in range(MAX_TOOL_CALLS + 2)],
        }
    )
    return ToolRegistry(jira=JiraConnector(transport, browse_base_url="https://j"))


async def test_each_wrapper_returns_a_full_toolcall() -> None:
    registry = _registry()
    call = await registry.search_jira("checkout slow")
    assert call.name == "search_jira"
    assert call.args == {"query": "checkout slow"}
    assert isinstance(call.result, ToolSuccess)
    assert call.evidence()[0].ref == "PAY-1"

    created = await registry.create_ticket(project_key="P", summary="s", description="d")
    assert created.name == "create_ticket"
    assert created.args == {"project_key": "P", "summary": "s"}

    linked = await registry.link_duplicate(duplicate_key="PAY-9", canonical_key="PAY-1")
    assert linked.name == "link_duplicate"
    assert registry.calls_made == 3


async def test_the_cap_bites_at_max_tool_calls_and_reset_clears_it() -> None:
    registry = _registry()
    for _ in range(MAX_TOOL_CALLS):
        await registry.search_jira("q")
    assert registry.calls_made == MAX_TOOL_CALLS
    with pytest.raises(ToolBudgetError, match=f"{MAX_TOOL_CALLS} cap"):
        await registry.search_jira("one too many")

    registry.reset()
    assert registry.calls_made == 0
    await registry.search_jira("fresh budget")


def test_issue_url_spends_no_call() -> None:
    registry = _registry()
    assert registry.issue_url("PAY-3") == "https://j/browse/PAY-3"
    assert registry.calls_made == 0
