"""The connector contract — how every tool looks to the orchestrator (§3)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from firsthand.contracts.draft import Contract, Evidence

#: Hard cap on evidence lookups per request (§7). Without it an ambiguous or
#: adversarial message turns one request into an open-ended bill.
MAX_TOOL_CALLS = 6

ToolName = Literal[
    "search_jira",
    "search_git_history",
    "search_design_docs",
    "create_ticket",
    "link_duplicate",
]


class ToolSuccess(Contract):
    """A connector returns evidence, never a conclusion."""

    evidence: list[Evidence] = Field(default_factory=list)

    @property
    def found_evidence(self) -> bool:
        """False is an explicit no-evidence-found state, not a gap to paper over (§5)."""
        return bool(self.evidence)


class ToolError(Contract):
    """A connector failure, surfaced rather than swallowed."""

    error: str = Field(min_length=1)


ToolResult = ToolSuccess | ToolError


class ToolCall(Contract):
    """One call the orchestrator made, and what came back."""

    name: ToolName
    args: dict[str, Any] = Field(default_factory=dict)
    result: ToolResult | None = None

    @property
    def failed(self) -> bool:
        """Whether this call came back as an error."""
        return isinstance(self.result, ToolError)

    def evidence(self) -> list[Evidence]:
        """Evidence from this call — empty on error or while still pending."""
        return self.result.evidence if isinstance(self.result, ToolSuccess) else []
