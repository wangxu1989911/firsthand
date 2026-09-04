"""The ``search_design_docs`` connector end to end, against fixture docs."""

from __future__ import annotations

import pathlib
import sys
import types

import httpx
import pytest

from firsthand.connectors.docs import DesignDocsConnector, DocPage, FixtureProvider
from firsthand.connectors.docs.connector import _default_decryptor
from firsthand.connectors.docs.providers import ConfluenceProvider
from firsthand.contracts import ConnectorConfig, ToolCall, ToolError, ToolSuccess

FIXTURE_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "docs"


def _connector(*, max_results: int = 5) -> DesignDocsConnector:
    return DesignDocsConnector(FixtureProvider.from_directory(FIXTURE_DIR), max_results=max_results)


class _RaisingProvider:
    """A provider whose fetch always raises the exception it was given."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def fetch(self, query: str, *, limit: int) -> list[DocPage]:
        raise self._exc

    async def aclose(self) -> None:
        return None


def test_a_non_positive_max_results_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_results"):
        DesignDocsConnector(FixtureProvider([]), max_results=0)


async def test_search_returns_the_decision_passage_as_grounded_evidence() -> None:
    result = await _connector().search("dark mode theme for the dashboard")
    assert isinstance(result, ToolSuccess)
    assert result.found_evidence
    top = result.evidence[0]
    assert top.source == "docs"
    assert top.retrieved_by == "search_design_docs"
    assert top.ref == "https://docs.example.com/design/dark-mode-decision"
    assert "will not build a dark mode" in top.snippet
    # It surfaces the passage; it does not conclude "already decided" itself.
    assert isinstance(top.snippet, str)


async def test_search_with_no_match_is_an_explicit_empty_success() -> None:
    result = await _connector().search("quokka xylophone zeppelin")
    assert isinstance(result, ToolSuccess)
    assert result.evidence == []
    assert not result.found_evidence


async def test_search_respects_an_explicit_limit() -> None:
    result = await _connector().search("issues export sso dark mode offline", limit=1)
    assert isinstance(result, ToolSuccess)
    assert len(result.evidence) == 1


async def test_search_rejects_a_blank_query() -> None:
    result = await _connector().search("   ")
    assert isinstance(result, ToolError)
    assert "non-empty" in result.error


async def test_search_rejects_a_non_positive_limit() -> None:
    result = await _connector().search("dark mode", limit=0)
    assert isinstance(result, ToolError)
    assert result.error == "limit must be positive"


async def test_search_maps_a_timeout_to_a_tool_error() -> None:
    connector = DesignDocsConnector(_RaisingProvider(httpx.TimeoutException("slow")))
    result = await connector.search("dark mode")
    assert isinstance(result, ToolError)
    assert result.error == "docs provider timed out"


async def test_search_maps_an_http_status_error_to_a_tool_error() -> None:
    response = httpx.Response(503, request=httpx.Request("GET", "https://acme.example"))
    exc = httpx.HTTPStatusError("boom", request=response.request, response=response)
    connector = DesignDocsConnector(_RaisingProvider(exc))
    result = await connector.search("dark mode")
    assert isinstance(result, ToolError)
    assert result.error == "docs provider returned HTTP 503"


async def test_search_maps_a_transport_error_to_a_tool_error() -> None:
    connector = DesignDocsConnector(_RaisingProvider(httpx.ConnectError("no route")))
    result = await connector.search("dark mode")
    assert isinstance(result, ToolError)
    assert result.error == "could not reach docs provider"


async def test_search_maps_an_unreadable_response_body_to_a_tool_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="{ not json")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://acme.atlassian.net"
    )
    provider = ConfluenceProvider(
        base_url="https://acme.atlassian.net", credential="t", client=client
    )
    result = await DesignDocsConnector(provider).search("dark mode")
    assert isinstance(result, ToolError)
    assert result.error == "could not reach docs provider"


async def test_run_rejects_a_call_for_a_different_tool() -> None:
    result = await _connector().run(ToolCall(name="search_jira", args={"query": "x"}))
    assert isinstance(result, ToolError)
    assert "cannot handle" in result.error


async def test_run_requires_a_string_query_argument() -> None:
    result = await _connector().run(ToolCall(name="search_design_docs", args={"query": 7}))
    assert isinstance(result, ToolError)
    assert "string 'query'" in result.error


async def test_run_passes_an_integer_limit_through() -> None:
    call = ToolCall(
        name="search_design_docs", args={"query": "sso dark export offline", "limit": 2}
    )
    result = await _connector().run(call)
    assert isinstance(result, ToolSuccess)
    assert len(result.evidence) == 2


async def test_run_ignores_a_boolean_limit() -> None:
    call = ToolCall(name="search_design_docs", args={"query": "dark mode", "limit": True})
    result = await _connector().run(call)
    assert isinstance(result, ToolSuccess)


async def test_run_ignores_a_non_integer_limit() -> None:
    call = ToolCall(name="search_design_docs", args={"query": "dark mode", "limit": "lots"})
    result = await _connector().run(call)
    assert isinstance(result, ToolSuccess)


async def test_run_happy_path_returns_evidence() -> None:
    call = ToolCall(name="search_design_docs", args={"query": "single sign-on saml"})
    result = await _connector().run(call)
    assert isinstance(result, ToolSuccess)
    assert result.evidence[0].ref == "https://docs.example.com/design/sso-saml-support"


async def test_aclose_delegates_to_the_provider() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []}))
    client = httpx.AsyncClient(transport=transport, base_url="https://acme.atlassian.net")
    connector = DesignDocsConnector(
        ConfluenceProvider(base_url="https://acme.atlassian.net", credential="t", client=client)
    )
    await connector.aclose()
    assert client.is_closed


def _docs_config(*, connector_type: str = "docs") -> ConnectorConfig:
    return ConnectorConfig(
        type=connector_type,  # type: ignore[arg-type]
        base_url="https://acme.atlassian.net",
        credential="cipher",
        updated_by="admin",
    )


def test_from_config_rejects_a_non_docs_connector() -> None:
    with pytest.raises(ValueError, match="'docs' connector"):
        DesignDocsConnector.from_config(_docs_config(connector_type="jira"))


async def test_from_config_decrypts_the_credential_and_builds_a_working_connector() -> None:
    seen: list[str] = []

    def fake_decrypt(ciphertext: str) -> str:
        seen.append(ciphertext)
        return "me@acme.io:token"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://acme.atlassian.net"
    )
    connector = DesignDocsConnector.from_config(_docs_config(), decrypt=fake_decrypt, client=client)
    result = await connector.search("dark mode")
    assert isinstance(result, ToolSuccess)
    assert result.evidence == []
    assert seen == ["cipher"]


async def test_from_config_uses_the_default_decryptor_when_none_is_given() -> None:
    client = httpx.AsyncClient(base_url="https://acme.atlassian.net")
    connector = DesignDocsConnector.from_config(_docs_config(), client=client)
    assert isinstance(connector, DesignDocsConnector)
    await connector.aclose()


def test_default_decryptor_passes_through_when_the_secrets_module_is_absent() -> None:
    sys.modules.pop("firsthand.secrets", None)
    assert _default_decryptor("still-ciphertext") == "still-ciphertext"


def test_default_decryptor_uses_firsthand_secrets_when_it_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_decrypt(ciphertext: str) -> str:
        return f"plain::{ciphertext}"

    fake = types.ModuleType("firsthand.secrets")
    fake.decrypt = fake_decrypt  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "firsthand.secrets", fake)
    assert _default_decryptor("abc") == "plain::abc"
