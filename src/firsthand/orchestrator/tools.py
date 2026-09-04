"""Tool dispatch with the §7 budget baked in.

Every evidence lookup or tracker mutation the orchestrator makes goes through
here, so the ``MAX_TOOL_CALLS`` cap is enforced in exactly one place. The cap is
per inbound request: :meth:`ToolRegistry.reset` is called at the top of each
orchestrator turn.
"""

from __future__ import annotations

from firsthand.connectors.jira import JiraConnector
from firsthand.contracts import MAX_TOOL_CALLS, ToolCall


class ToolBudgetError(RuntimeError):
    """The request tried to exceed ``MAX_TOOL_CALLS`` evidence/tracker calls (§7)."""


class ToolRegistry:
    """Wraps the connectors and counts calls against the cap."""

    def __init__(self, *, jira: JiraConnector) -> None:
        self._jira = jira
        self._calls = 0

    @property
    def calls_made(self) -> int:
        """Calls spent since the last :meth:`reset`."""
        return self._calls

    def reset(self) -> None:
        """Zero the counter at the start of a request."""
        self._calls = 0

    def _spend(self, name: str) -> None:
        if self._calls >= MAX_TOOL_CALLS:
            raise ToolBudgetError(
                f"{name} would be call {self._calls + 1}, over the {MAX_TOOL_CALLS} cap (§7)"
            )
        self._calls += 1

    def issue_url(self, key: str) -> str:
        """The followable URL for an issue key (no call spent)."""
        return self._jira.issue_url(key)

    async def search_jira(self, query: str) -> ToolCall:
        self._spend("search_jira")
        result = await self._jira.search_jira(query)
        return ToolCall(name="search_jira", args={"query": query}, result=result)

    async def create_ticket(self, *, project_key: str, summary: str, description: str) -> ToolCall:
        self._spend("create_ticket")
        result = await self._jira.create_ticket(
            project_key=project_key, summary=summary, description=description
        )
        return ToolCall(
            name="create_ticket",
            args={"project_key": project_key, "summary": summary},
            result=result,
        )

    async def link_duplicate(self, *, duplicate_key: str, canonical_key: str) -> ToolCall:
        self._spend("link_duplicate")
        result = await self._jira.link_duplicate(
            duplicate_key=duplicate_key, canonical_key=canonical_key
        )
        return ToolCall(
            name="link_duplicate",
            args={"duplicate_key": duplicate_key, "canonical_key": canonical_key},
            result=result,
        )
