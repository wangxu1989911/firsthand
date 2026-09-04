"""The Jira connector: ``search_jira``, ``create_ticket``, ``link_duplicate``.

Every method returns a ``ToolResult`` — ``ToolSuccess`` carrying zero or more
``Evidence`` rows, or ``ToolError``. A search that matches nothing returns
``ToolSuccess`` with an empty list: an explicit "nothing found", never a
fabricated hit (§5). The connector reports what Jira said and stops there; the
orchestrator decides what it means (§3).
"""

from __future__ import annotations

from typing import Any

from firsthand.connectors.jira.transport import JiraTransport, JiraTransportError
from firsthand.contracts import Evidence, ToolError, ToolResult, ToolSuccess

_SEARCH_PATH = "/rest/api/3/search"
_ISSUE_PATH = "/rest/api/3/issue"
_LINK_PATH = "/rest/api/3/issueLink"


def _text_from_adf(node: Any) -> str:
    """Flatten Atlassian Document Format (or a plain string) to text for a snippet."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            return str(node["text"])
        return " ".join(_text_from_adf(child) for child in node.get("content", []))
    if isinstance(node, list):
        return " ".join(_text_from_adf(child) for child in node)
    return ""


def _snippet(fields: dict[str, Any]) -> str:
    summary = str(fields.get("summary") or "").strip()
    status = str((fields.get("status") or {}).get("name") or "").strip()
    description = _text_from_adf(fields.get("description")).strip()
    parts = [part for part in (summary, description) if part]
    body = " — ".join(parts) or "(no summary)"
    return f"{body} [{status}]" if status else body


class JiraConnector:
    """Turns Jira REST responses into ``Evidence``. Holds no opinions."""

    def __init__(self, transport: JiraTransport, *, browse_base_url: str) -> None:
        self._transport = transport
        self._browse = browse_base_url.rstrip("/")

    def issue_url(self, key: str) -> str:
        """The human-followable URL for an issue key."""
        return f"{self._browse}/browse/{key}"

    async def search_jira(self, query: str, *, max_results: int = 5) -> ToolResult:
        """Free-text search. Returns one ``Evidence`` per matched issue."""
        jql = f'text ~ "{_escape(query)}" ORDER BY updated DESC'
        try:
            body = await self._transport.get(
                _SEARCH_PATH,
                {
                    "jql": jql,
                    "maxResults": max_results,
                    "fields": "summary,status,description",
                },
            )
        except JiraTransportError as exc:
            return ToolError(error=f"jira search failed: {exc}")

        issues = body.get("issues") or []
        evidence = [
            Evidence(
                source="jira",
                ref=str(issue.get("key") or "UNKNOWN"),
                snippet=_snippet(issue.get("fields") or {}),
                retrieved_by="search_jira",
            )
            for issue in issues
        ]
        return ToolSuccess(evidence=evidence)

    async def create_ticket(
        self,
        *,
        project_key: str,
        summary: str,
        description: str,
        issue_type: str = "Task",
    ) -> ToolResult:
        """Create an issue. The created key comes back as a single ``Evidence`` row.

        ``ToolResult`` has no dedicated "created id" channel, so the new key
        travels as an evidence ref — still a real, followable reference — tagged
        ``retrieved_by="create_ticket"`` so the orchestrator can tell it apart
        from a search hit.
        """
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": issue_type},
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": description}]}
                    ],
                },
            }
        }
        try:
            body = await self._transport.post(_ISSUE_PATH, payload)
        except JiraTransportError as exc:
            return ToolError(error=f"jira create failed: {exc}")

        key = str(body.get("key") or "")
        if not key:
            return ToolError(error=f"jira create returned no key: {body!r}")
        return ToolSuccess(
            evidence=[
                Evidence(
                    source="jira",
                    ref=key,
                    snippet=f"created {key}: {summary}",
                    retrieved_by="create_ticket",
                )
            ]
        )

    async def link_duplicate(self, *, duplicate_key: str, canonical_key: str) -> ToolResult:
        """Record that ``duplicate_key`` duplicates ``canonical_key``."""
        payload = {
            "type": {"name": "Duplicate"},
            "inwardIssue": {"key": duplicate_key},
            "outwardIssue": {"key": canonical_key},
        }
        try:
            await self._transport.post(_LINK_PATH, payload)
        except JiraTransportError as exc:
            return ToolError(error=f"jira link failed: {exc}")
        return ToolSuccess(
            evidence=[
                Evidence(
                    source="jira",
                    ref=canonical_key,
                    snippet=f"{duplicate_key} linked as duplicate of {canonical_key}",
                    retrieved_by="link_duplicate",
                )
            ]
        )


def _escape(query: str) -> str:
    """Neutralise the quote and backslash that would break out of a JQL string."""
    return query.replace("\\", "\\\\").replace('"', '\\"')
