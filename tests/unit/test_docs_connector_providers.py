"""Providers: markup handling, the Confluence HTTP path (mocked), fixtures."""

from __future__ import annotations

import pathlib
from collections.abc import Callable

import httpx
import pytest

from firsthand.connectors.docs.providers import (
    ConfluenceProvider,
    FixtureProvider,
    _escape_cql,
    build_confluence_client,
    strip_markup,
)

FIXTURE_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "docs"


def test_strip_markup_turns_storage_xhtml_into_plain_text_with_breaks() -> None:
    markup = (
        "<h1>Title</h1><p>Hello &amp; welcome</p>"
        "<p>Second<br/>line</p><ul><li>a</li><li>b</li></ul>"
    )
    text = strip_markup(markup)
    assert "<" not in text
    assert "Hello & welcome" in text
    assert "Second\n\nline" in text
    assert text.startswith("Title")


async def test_build_confluence_client_uses_basic_auth_for_an_email_token_pair() -> None:
    client = build_confluence_client("https://acme.atlassian.net/", "me@acme.io:secret", 5.0)
    assert isinstance(client.auth, httpx.BasicAuth)
    assert str(client.base_url) == "https://acme.atlassian.net"
    await client.aclose()


async def test_build_confluence_client_uses_bearer_for_a_bare_token() -> None:
    client = build_confluence_client("https://acme.example", "pat-123", 5.0)
    assert client.headers["authorization"] == "Bearer pat-123"
    await client.aclose()


def test_escape_cql_escapes_backslashes_and_quotes() -> None:
    assert _escape_cql(r'a\b"c') == r"a\\b\"c"


async def test_confluence_provider_builds_its_own_client_when_none_is_given() -> None:
    provider = ConfluenceProvider(
        base_url="https://acme.atlassian.net", credential="me@acme.io:tok"
    )
    assert isinstance(provider._client, httpx.AsyncClient)
    await provider.aclose()


Handler = Callable[[httpx.Request], httpx.Response]


def _provider(handler: Handler, *, page_limit: int = 25) -> ConfluenceProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://acme.atlassian.net")
    return ConfluenceProvider(
        base_url="https://acme.atlassian.net", credential="t", client=client, page_limit=page_limit
    )


async def test_confluence_fetch_maps_results_to_doc_pages() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "_links": {"base": "https://acme.atlassian.net/wiki"},
                "results": [
                    {
                        "title": "Dark mode decision",
                        "_links": {"webui": "/spaces/DESIGN/pages/42/Dark+mode"},
                        "space": {"name": "Product Design"},
                        "body": {"storage": {"value": "<p>Decision: not now.</p>"}},
                    }
                ],
            },
        )

    pages = await _provider(handler).fetch('dark "theme"', limit=5)
    assert len(pages) == 1
    assert pages[0].url == "https://acme.atlassian.net/wiki/spaces/DESIGN/pages/42/Dark+mode"
    assert pages[0].space == "Product Design"
    assert pages[0].text == "Decision: not now."
    # The query is escaped into the CQL literal, not passed through raw.
    assert 'text ~ "dark \\"theme\\""' in seen[0].url.params["cql"]


async def test_confluence_fetch_drops_results_that_cannot_be_cited() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "No link here", "body": {"storage": {"value": "x"}}},
                    {"_links": {"webui": "/p/1"}, "title": ""},
                    {
                        "title": "Good",
                        "_links": {"webui": "https://elsewhere.example/p/2"},
                    },
                    {
                        "title": "Odd body type",
                        "_links": {"webui": "/p/w"},
                        "body": {"storage": {"value": 12345}},
                    },
                ]
            },
        )

    pages = await _provider(handler).fetch("q", limit=5)
    assert [p.url for p in pages] == [
        "https://elsewhere.example/p/2",
        "https://acme.atlassian.net/p/w",
    ]
    assert pages[0].space is None
    # A non-string body value degrades to empty text rather than raising.
    assert [p.text for p in pages] == ["", ""]


async def test_confluence_fetch_falls_back_to_the_client_base_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"title": "T", "_links": {"webui": "/p/9"}}]},
        )

    pages = await _provider(handler).fetch("q", limit=5)
    assert pages[0].url == "https://acme.atlassian.net/p/9"


async def test_confluence_fetch_tolerates_a_payload_with_no_results_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert await _provider(handler).fetch("q", limit=5) == []


async def test_confluence_fetch_clamps_the_requested_limit() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    await _provider(handler, page_limit=3).fetch("q", limit=999)
    assert seen[0].url.params["limit"] == "3"
    await _provider(handler, page_limit=3).fetch("q", limit=0)
    assert seen[1].url.params["limit"] == "1"


async def test_confluence_fetch_raises_on_an_http_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    with pytest.raises(httpx.HTTPStatusError):
        await _provider(handler).fetch("q", limit=5)


async def test_confluence_fetch_slices_to_the_caller_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"title": f"T{n}", "_links": {"webui": f"/p/{n}"}} for n in range(5)]
            },
        )

    pages = await _provider(handler).fetch("q", limit=2)
    assert [p.url for p in pages] == [
        "https://acme.atlassian.net/p/0",
        "https://acme.atlassian.net/p/1",
    ]


async def test_confluence_provider_closes_its_client() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []}))
    client = httpx.AsyncClient(transport=transport, base_url="https://acme.atlassian.net")
    provider = ConfluenceProvider(
        base_url="https://acme.atlassian.net", credential="t", client=client
    )
    await provider.aclose()
    assert client.is_closed


async def test_fixture_provider_loads_every_page_and_ignores_the_query() -> None:
    provider = FixtureProvider.from_directory(FIXTURE_DIR)
    pages = await provider.fetch("whatever", limit=1)
    assert {p.title for p in pages} == {
        "Dark mode: decision record",
        "SSO and SAML support",
        "Bulk CSV export of issues",
        "Mobile offline mode",
    }
    await provider.aclose()


async def test_fixture_provider_accepts_an_explicit_page_list() -> None:
    assert await FixtureProvider([]).fetch("q", limit=1) == []
