"""The HTTP seam: CallBudget, and GitHubHost driven through httpx.MockTransport.

No network — every response is a fixture from tests/fixtures/git/ or a small
inline payload standing in for one the API would send.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from firsthand.connectors.git.hosts import (
    MAX_COMMIT_PAGES,
    UNKNOWN_DATE,
    CallBudget,
    GitHubHost,
    _author_of,
    _clip,
    _parsed_date,
    make_host,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "git"


def _load(name: str) -> object:
    return json.loads((_FIXTURES / name).read_text())


Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )


def _boom(_: httpx.Request) -> httpx.Response:  # pragma: no cover - asserts non-call
    raise AssertionError("no request should have been made")


# --------------------------------------------------------------------------- budget


def test_budget_rejects_a_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        CallBudget(0)


def test_budget_counts_down_and_then_refuses() -> None:
    budget = CallBudget(2)
    assert budget.limit == 2
    assert budget.spend() is True
    assert budget.spend() is True
    assert budget.used == 2
    assert budget.exhausted is True
    assert budget.spend() is False


# ----------------------------------------------------------------------------- _clip


def test_clip_leaves_short_text_and_truncates_long_text() -> None:
    assert _clip("  hi  ") == "hi"
    assert _clip("x" * 20, 10).endswith("…")
    assert len(_clip("x" * 20, 10)) == 10


# ------------------------------------------------------------------- search_commits


async def test_search_commits_maps_items_and_skips_blank_messages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/commits"
        assert "repo:acme/store" in request.url.params["q"]
        return httpx.Response(200, json=_load("search_commits_checkout.json"))

    async with _client(handler) as client:
        hits = await GitHubHost(client, CallBudget(5)).search_commits("acme/store", "checkout", 10)

    assert len(hits) == 1
    assert hits[0].repo == "acme/store"
    assert hits[0].sha.startswith("aaa111")
    assert "coupon is removed" in hits[0].message


async def test_search_commits_returns_nothing_once_the_budget_is_spent() -> None:
    budget = CallBudget(1)
    budget.spend()
    async with _client(_boom) as client:
        assert await GitHubHost(client, budget).search_commits("acme/store", "x", 10) == []


async def test_search_commits_falls_back_to_the_requested_repo_name() -> None:
    payload = {
        "items": [
            {
                "sha": "d" * 40,
                "html_url": "",
                "commit": {"message": "hello", "author": {"date": "2026-01-01T00:00:00Z"}},
            }
        ]
    }

    async with _client(lambda _: httpx.Response(200, json=payload)) as client:
        hits = await GitHubHost(client, CallBudget(5)).search_commits("acme/store", "x", 10)
    assert hits[0].repo == "acme/store"


# -------------------------------------------------------------- search_pull_requests


async def test_search_pull_requests_joins_title_and_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/issues"
        assert "type:pr" in request.url.params["q"]
        return httpx.Response(200, json=_load("search_issues_checkout.json"))

    async with _client(handler) as client:
        hits = await GitHubHost(client, CallBudget(5)).search_pull_requests(
            "acme/store", "checkout", 10
        )

    assert hits[0].number == 214
    assert hits[0].title.startswith("Rework checkout")
    assert "server-side" in hits[0].body


async def test_search_pull_requests_keeps_a_title_only_hit_and_drops_an_empty_one() -> None:
    payload = {
        "items": [
            {"number": 1, "title": "Just a title", "body": None, "html_url": "u"},
            {"number": 2, "title": "   ", "body": "   ", "html_url": "u"},
        ]
    }
    async with _client(lambda _: httpx.Response(200, json=payload)) as client:
        hits = await GitHubHost(client, CallBudget(5)).search_pull_requests("acme/store", "x", 10)

    assert [h.number for h in hits] == [1]
    assert hits[0].body == ""


async def test_search_pull_requests_stops_when_the_budget_is_spent() -> None:
    budget = CallBudget(1)
    budget.spend()
    async with _client(_boom) as client:
        assert await GitHubHost(client, budget).search_pull_requests("acme/store", "x", 1) == []


# --------------------------------------------------------------- commits_touching


def _since() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


async def test_commits_touching_walks_one_short_page_with_detail() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/repos/acme/store/commits":
            return httpx.Response(200, json=_load("commits_checkout_dir.json"))
        sha = request.url.path.rsplit("/", 1)[-1][:6]
        return httpx.Response(200, json=_load(f"commit_detail_{sha}.json"))

    async with _client(handler) as client:
        records, capped = await GitHubHost(client, CallBudget(20)).commits_touching(
            "acme/store", "src/checkout/", _since(), detail_limit=10
        )

    assert capped is False
    assert [r.author for r in records] == ["danalee", "danalee", "Priya Nair"]
    assert records[0].additions == 45 and records[0].files_changed == 2
    assert records[0].committed_at.year == 2026


async def test_commits_touching_honours_the_detail_sample_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/store/commits":
            return httpx.Response(200, json=_load("commits_checkout_dir.json"))
        sha = request.url.path.rsplit("/", 1)[-1][:6]
        return httpx.Response(200, json=_load(f"commit_detail_{sha}.json"))

    async with _client(handler) as client:
        records, capped = await GitHubHost(client, CallBudget(20)).commits_touching(
            "acme/store", "src/checkout/", _since(), detail_limit=1
        )

    assert [r.additions for r in records] == [45, None, None]
    assert capped is False


async def test_commits_touching_flags_capped_when_the_listing_budget_runs_out() -> None:
    async with _client(lambda _: httpx.Response(200, json=[])) as client:
        budget = CallBudget(1)
        budget.spend()
        records, capped = await GitHubHost(client, budget).commits_touching(
            "acme/store", "x", _since(), detail_limit=0
        )
    assert records == []
    assert capped is True


async def test_commits_touching_flags_capped_when_detail_budget_runs_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/store/commits":
            return httpx.Response(200, json=_load("commits_checkout_dir.json"))
        raise AssertionError("detail should never be reached")

    async with _client(handler) as client:
        records, capped = await GitHubHost(client, CallBudget(1)).commits_touching(
            "acme/store", "src/checkout/", _since(), detail_limit=10
        )

    assert capped is True
    assert all(r.additions is None for r in records)
    assert len(records) == 3


async def test_commits_touching_breaks_on_a_non_list_body() -> None:
    async with _client(lambda _: httpx.Response(200, json={})) as client:
        records, capped = await GitHubHost(client, CallBudget(5)).commits_touching(
            "acme/store", "x", _since(), detail_limit=0
        )
    assert (records, capped) == ([], False)


async def test_commits_touching_paginates_full_pages_until_it_caps() -> None:
    full_page = [
        {
            "sha": f"{i:040d}",
            "commit": {"author": {"name": "Bot", "date": "2026-07-01T00:00:00Z"}},
            "author": {"login": "bot"},
        }
        for i in range(100)
    ]
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pages.append(int(request.url.params["page"]))
        return httpx.Response(200, json=full_page)

    async with _client(handler) as client:
        records, capped = await GitHubHost(client, CallBudget(50)).commits_touching(
            "acme/store", "x", _since(), detail_limit=0
        )

    assert pages == list(range(1, MAX_COMMIT_PAGES + 1))
    assert capped is True
    assert len(records) == 100 * MAX_COMMIT_PAGES


async def test_commits_touching_caps_when_the_page_budget_empties_mid_walk() -> None:
    full_page = [
        {
            "sha": f"{i:040d}",
            "commit": {"author": {"name": "Bot", "date": "2026-07-01T00:00:00Z"}},
            "author": {"login": "bot"},
        }
        for i in range(100)
    ]

    async with _client(lambda _: httpx.Response(200, json=full_page)) as client:
        records, capped = await GitHubHost(client, CallBudget(2)).commits_touching(
            "acme/store", "x", _since(), detail_limit=0
        )

    assert capped is True
    assert len(records) == 200


# ------------------------------------------------------------------ small helpers


def test_author_of_prefers_login_then_name_then_unknown() -> None:
    assert _author_of({"author": {"login": "octocat"}}) == "octocat"
    assert _author_of({"author": None, "commit": {"author": {"name": "Grace"}}}) == "Grace"
    assert _author_of({"author": None, "commit": {}}) == "unknown"
    assert _author_of({}) == "unknown"


def test_parsed_date_handles_missing_and_malformed_timestamps() -> None:
    assert _parsed_date({"commit": {"author": {"date": "2026-08-20T12:00:00Z"}}}).year == 2026
    assert _parsed_date({}) == UNKNOWN_DATE
    assert _parsed_date({"commit": {}}) == UNKNOWN_DATE
    assert _parsed_date({"commit": {"author": {"date": "nonsense"}}}) == UNKNOWN_DATE


async def test_make_host_builds_github_and_refuses_gitlab() -> None:
    async with _client(lambda _: httpx.Response(204)) as dummy:
        assert isinstance(make_host("github", dummy, CallBudget(1)), GitHubHost)
        with pytest.raises(NotImplementedError, match="gitlab"):
            make_host("gitlab", dummy, CallBudget(1))
