"""The real Jira transport is HTTP only — MockTransport pins its shape and errors."""

from __future__ import annotations

import base64

import httpx
import pytest

from firsthand.connectors.jira.transport import JiraHTTPTransport, JiraTransportError


def _transport(handler: object) -> JiraHTTPTransport:
    mock = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = httpx.AsyncClient(base_url="https://jira.test", transport=mock)
    return JiraHTTPTransport(
        base_url="https://jira.test", email="bot@corp", api_token="tok", client=client
    )


async def test_get_sends_basic_auth_and_returns_json() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["path"] = request.url.path
        return httpx.Response(200, json={"issues": []})

    body = await _transport(handler).get("/rest/api/3/search", {"jql": "x"})
    assert body == {"issues": []}
    expected = base64.b64encode(b"bot@corp:tok").decode()
    assert seen["auth"] == f"Basic {expected}"


async def test_a_4xx_is_raised_as_a_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with pytest.raises(JiraTransportError, match="403"):
        await _transport(handler).get("/x", {})


async def test_a_network_error_on_post_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(JiraTransportError, match="POST /x failed"):
        await _transport(handler).post("/x", {"a": 1})


async def test_a_network_error_on_get_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(JiraTransportError, match="GET /x failed"):
        await _transport(handler).get("/x", {})


async def test_post_returns_parsed_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"key": "PAY-1"})

    assert await _transport(handler).post("/rest/api/3/issue", {}) == {"key": "PAY-1"}


async def test_aclose_closes_only_an_owned_client() -> None:
    client = httpx.AsyncClient(base_url="https://jira.test")
    transport = JiraHTTPTransport(
        base_url="https://jira.test", email="e", api_token="t", client=client
    )
    await transport.aclose()
    assert not client.is_closed
    await client.aclose()

    owned = JiraHTTPTransport(base_url="https://jira.test", email="e", api_token="t")
    await owned.aclose()
