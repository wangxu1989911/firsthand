"""The Jira connector returns Evidence or ToolError — never a fabricated hit (§5)."""

from __future__ import annotations

import pytest

from firsthand.connectors.jira import JiraConnector, RecordedJiraTransport, search_response
from firsthand.connectors.jira.transport import JiraTransportError
from firsthand.contracts import ToolError, ToolSuccess


def _connector(responses: dict[str, object]) -> tuple[JiraConnector, RecordedJiraTransport]:
    transport = RecordedJiraTransport(responses)
    return JiraConnector(transport, browse_base_url="https://jira.test/"), transport


async def test_search_maps_each_issue_to_one_evidence_row() -> None:
    connector, transport = _connector(
        {"GET /rest/api/3/search": search_response(("PAY-1", "checkout slow", "Open"))}
    )
    result = await connector.search_jira('checkout "slow"')
    assert isinstance(result, ToolSuccess)
    assert result.found_evidence
    ev = result.evidence[0]
    assert ev.source == "jira"
    assert ev.ref == "PAY-1"
    assert "checkout slow" in ev.snippet and "[Open]" in ev.snippet
    assert ev.retrieved_by == "search_jira"
    # the quote in the query is escaped into the JQL, not left to break it
    assert '\\"slow\\"' in transport.calls[0][2]["jql"]


async def test_search_with_no_hits_is_an_explicit_empty_success() -> None:
    connector, _ = _connector({"GET /rest/api/3/search": {"issues": []}})
    result = await connector.search_jira("nothing matches")
    assert isinstance(result, ToolSuccess)
    assert result.evidence == []
    assert result.found_evidence is False


async def test_search_flattens_an_adf_description_and_survives_a_missing_key() -> None:
    body = {
        "issues": [
            {
                "key": "PAY-2",
                "fields": {
                    "summary": "latency",
                    "description": {
                        "type": "doc",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "p95 up"}]}
                        ],
                    },
                },
            },
            {"fields": {}},
        ]
    }
    connector, _ = _connector({"GET /rest/api/3/search": body})
    result = await connector.search_jira("latency")
    assert isinstance(result, ToolSuccess)
    assert "p95 up" in result.evidence[0].snippet
    assert result.evidence[1].ref == "UNKNOWN"
    assert result.evidence[1].snippet == "(no summary)"


async def test_search_handles_a_plain_string_description_and_a_list_node() -> None:
    body = {
        "issues": [
            {"key": "PAY-3", "fields": {"summary": "a", "description": "plain string body"}},
            {
                "key": "PAY-5",
                "fields": {
                    "summary": "c",
                    "description": [
                        {"type": "text", "text": "bare"},
                        {"type": "text", "text": "list"},
                    ],
                },
            },
            {
                "key": "PAY-4",
                "fields": {
                    "summary": "b",
                    "description": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "one"},
                                    {"type": "text", "text": "two"},
                                ],
                            }
                        ],
                    },
                },
            },
        ]
    }
    connector, _ = _connector({"GET /rest/api/3/search": body})
    result = await connector.search_jira("x")
    assert isinstance(result, ToolSuccess)
    assert "plain string body" in result.evidence[0].snippet
    assert "bare list" in result.evidence[1].snippet
    assert "one two" in result.evidence[2].snippet


async def test_a_transport_failure_on_search_becomes_a_tool_error() -> None:
    class _Boom:
        async def get(self, path: str, params: dict[str, object]) -> dict[str, object]:
            raise JiraTransportError("503")

        async def post(
            self, path: str, payload: dict[str, object]
        ) -> dict[str, object]:  # pragma: no cover
            raise AssertionError

    result = await JiraConnector(_Boom(), browse_base_url="https://j").search_jira("x")
    assert isinstance(result, ToolError)
    assert "jira search failed" in result.error


async def test_create_ticket_reports_the_new_key_as_evidence() -> None:
    connector, transport = _connector({"POST /rest/api/3/issue": {"key": "PAY-10"}})
    result = await connector.create_ticket(
        project_key="PAY", summary="checkout slow", description="redacted body"
    )
    assert isinstance(result, ToolSuccess)
    ev = result.evidence[0]
    assert ev.ref == "PAY-10"
    assert ev.retrieved_by == "create_ticket"
    sent = transport.calls[0][2]
    assert sent["fields"]["project"]["key"] == "PAY"
    assert sent["fields"]["description"]["content"][0]["content"][0]["text"] == "redacted body"


async def test_create_ticket_without_a_key_in_the_reply_is_a_tool_error() -> None:
    connector, _ = _connector({"POST /rest/api/3/issue": {"id": "123"}})
    result = await connector.create_ticket(project_key="PAY", summary="s", description="d")
    assert isinstance(result, ToolError)
    assert "no key" in result.error


async def test_create_ticket_transport_failure_is_a_tool_error() -> None:
    class _Boom:
        async def get(self, *a: object, **k: object) -> dict[str, object]:  # pragma: no cover
            raise AssertionError

        async def post(self, *a: object, **k: object) -> dict[str, object]:
            raise JiraTransportError("500")

    result = await JiraConnector(_Boom(), browse_base_url="https://j").create_ticket(
        project_key="P", summary="s", description="d"
    )
    assert isinstance(result, ToolError)
    assert "jira create failed" in result.error


async def test_link_duplicate_records_the_link_as_evidence() -> None:
    connector, transport = _connector({"POST /rest/api/3/issueLink": {}})
    result = await connector.link_duplicate(duplicate_key="PAY-10", canonical_key="PAY-1")
    assert isinstance(result, ToolSuccess)
    assert result.evidence[0].ref == "PAY-1"
    assert "duplicate of PAY-1" in result.evidence[0].snippet
    payload = transport.calls[0][2]
    assert payload["inwardIssue"]["key"] == "PAY-10"
    assert payload["type"]["name"] == "Duplicate"


async def test_link_duplicate_transport_failure_is_a_tool_error() -> None:
    class _Boom:
        async def get(self, *a: object, **k: object) -> dict[str, object]:  # pragma: no cover
            raise AssertionError

        async def post(self, *a: object, **k: object) -> dict[str, object]:
            raise JiraTransportError("400")

    result = await JiraConnector(_Boom(), browse_base_url="https://j").link_duplicate(
        duplicate_key="A", canonical_key="B"
    )
    assert isinstance(result, ToolError)


def test_issue_url_is_followable() -> None:
    connector, _ = _connector({})
    assert connector.issue_url("PAY-3") == "https://jira.test/browse/PAY-3"


async def test_recorded_transport_can_script_successive_calls() -> None:
    transport = RecordedJiraTransport(
        {"GET /rest/api/3/search": [{"issues": []}, search_response(("PAY-1", "s", "Open"))]}
    )
    connector = JiraConnector(transport, browse_base_url="https://j")
    assert (await connector.search_jira("a")).evidence == []  # type: ignore[union-attr]
    assert (await connector.search_jira("b")).evidence[0].ref == "PAY-1"  # type: ignore[union-attr]


async def test_recorded_transport_raises_on_an_unrecorded_call() -> None:
    transport = RecordedJiraTransport({})
    with pytest.raises(KeyError, match="no recorded Jira response"):
        await transport.get("/rest/api/3/search", {})


async def test_recorded_transport_raises_when_a_scripted_list_is_exhausted() -> None:
    transport = RecordedJiraTransport({"GET /rest/api/3/search": [{"issues": []}]})
    await transport.get("/rest/api/3/search", {})
    with pytest.raises(KeyError, match="exhausted"):
        await transport.get("/rest/api/3/search", {})
