"""GitHistoryConnector: arg validation, credential handling, and evidence shape."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from firsthand.connectors.git import connector as conn_mod
from firsthand.connectors.git.connector import (
    GitConnectorError,
    GitHistoryConnector,
    _identity,
    _load_decryptor,
    _web_base_url,
)
from firsthand.connectors.git.hosts import CommitHit, CommitRecord, PullRequestHit
from firsthand.connectors.git.settings import GitConnectorSettings
from firsthand.contracts import ConnectorConfig, ToolCall, ToolError, ToolSuccess

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "git"


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("FIRSTHAND_GIT_"):
            monkeypatch.delenv(key, raising=False)


def _load(name: str) -> Any:
    return json.loads((_FIXTURES / name).read_text())


def _cfg(
    *, base_url: str = "https://api.github.com", credential: str = "cipher"
) -> ConnectorConfig:
    return ConnectorConfig(type="git", base_url=base_url, credential=credential, updated_by="admin")


def _settings(**over: Any) -> GitConnectorSettings:
    base: dict[str, Any] = {"repos": "acme/store"}
    base.update(over)
    return GitConnectorSettings(**base)


class FakeHost:
    """A GitHost stand-in with canned returns, or an exception to raise."""

    def __init__(
        self,
        *,
        commits: list[CommitHit] | None = None,
        prs: list[PullRequestHit] | None = None,
        records: list[CommitRecord] | None = None,
        capped: bool = False,
        raises: Exception | None = None,
    ) -> None:
        self.commits = commits or []
        self.prs = prs or []
        self.records = records or []
        self.capped = capped
        self.raises = raises
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def search_commits(self, repo: str, query: str, limit: int) -> list[CommitHit]:
        self.calls.append(("commits", (repo, query, limit)))
        if self.raises is not None:
            raise self.raises
        return self.commits

    async def search_pull_requests(self, repo: str, query: str, limit: int) -> list[PullRequestHit]:
        self.calls.append(("prs", (repo, query, limit)))
        if self.raises is not None:
            raise self.raises
        return self.prs

    async def commits_touching(
        self, repo: str, path: str, since: Any, *, detail_limit: int
    ) -> tuple[list[CommitRecord], bool]:
        self.calls.append(("churn", (repo, path, detail_limit)))
        if self.raises is not None:
            raise self.raises
        return self.records, self.capped


def _connector(host: FakeHost, **kw: Any) -> GitHistoryConnector:
    return GitHistoryConnector(
        _cfg(), settings=_settings(**kw.pop("settings", {})), host=host, decryptor=lambda _: "tok"
    )


# --------------------------------------------------------------------- construction


def test_rejects_a_non_git_config() -> None:
    with pytest.raises(GitConnectorError, match="expected a git"):
        GitHistoryConnector(_cfg().model_copy(update={"type": "jira"}))


# ------------------------------------------------------------------- run() dispatch


async def test_run_refuses_a_foreign_tool() -> None:
    result = await _connector(FakeHost()).run(ToolCall(name="search_jira"))
    assert isinstance(result, ToolError)
    assert "not 'search_git_history'" in result.error


async def test_run_rejects_a_non_string_query() -> None:
    call = ToolCall(name="search_git_history", args={"query": 3})
    result = await _connector(FakeHost()).run(call)
    assert isinstance(result, ToolError)
    assert "'query' must be a string" in result.error


@pytest.mark.parametrize(
    "hints,message",
    [
        ([1, 2], "'path_hints' must be a list of strings"),
        (5, "'path_hints' must be a string or a list of strings"),
    ],
)
async def test_run_rejects_bad_path_hints(hints: Any, message: str) -> None:
    call = ToolCall(name="search_git_history", args={"query": "x", "path_hints": hints})
    result = await _connector(FakeHost()).run(call)
    assert isinstance(result, ToolError)
    assert result.error == message


async def test_run_passes_a_string_list_of_hints_through() -> None:
    host = FakeHost(records=[CommitRecord(sha="a", author="x", committed_at=_dt())])
    call = ToolCall(
        name="search_git_history",
        args={"query": "x", "path_hints": ["src/checkout", "", "/src/checkout/"]},
    )
    result = await _connector(host).run(call)
    assert isinstance(result, ToolSuccess)
    churn_paths = [args[1] for name, args in host.calls if name == "churn"]
    assert churn_paths == ["src/checkout"]


async def test_run_accepts_a_bare_string_hint() -> None:
    host = FakeHost(records=[CommitRecord(sha="a", author="x", committed_at=_dt())])
    call = ToolCall(
        name="search_git_history", args={"query": "checkout", "path_hints": "src/checkout/"}
    )
    result = await _connector(host).run(call)
    assert isinstance(result, ToolSuccess)
    assert ("churn", ("acme/store", "src/checkout", 25)) in host.calls


# ---------------------------------------------------------------- query/repo guards


async def test_empty_query_is_an_error() -> None:
    result = await _connector(FakeHost()).search_git_history(query="   ")
    assert isinstance(result, ToolError)
    assert "must not be empty" in result.error


async def test_an_over_long_query_is_an_error() -> None:
    result = await _connector(FakeHost()).search_git_history(query="x" * 300)
    assert isinstance(result, ToolError)
    assert "exceeds" in result.error


async def test_no_configured_repos_is_an_error() -> None:
    c = GitHistoryConnector(
        _cfg(), settings=_settings(repos=""), host=FakeHost(), decryptor=_identity
    )
    result = await c.search_git_history(query="x")
    assert isinstance(result, ToolError)
    assert "no repositories configured" in result.error


async def test_a_bad_repo_slug_is_an_error() -> None:
    c = GitHistoryConnector(
        _cfg(), settings=_settings(repos="not-a-repo"), host=FakeHost(), decryptor=_identity
    )
    result = await c.search_git_history(query="x")
    assert isinstance(result, ToolError)
    assert "not a valid owner/repo slug" in result.error


# -------------------------------------------------------------- credential handling


async def test_an_empty_credential_is_an_error() -> None:
    c = GitHistoryConnector(_cfg(credential=""), settings=_settings(), host=FakeHost())
    result = await c.search_git_history(query="x")
    assert isinstance(result, ToolError)
    assert "credential is empty" in result.error


async def test_a_decrypt_failure_is_reported_without_the_ciphertext() -> None:
    def explode(_: str) -> str:
        raise RuntimeError("bad key")

    c = GitHistoryConnector(_cfg(), settings=_settings(), host=FakeHost(), decryptor=explode)
    result = await c.search_git_history(query="x")
    assert isinstance(result, ToolError)
    assert result.error == "could not decrypt connector credential: RuntimeError"


async def test_an_empty_decrypted_token_is_an_error() -> None:
    c = GitHistoryConnector(_cfg(), settings=_settings(), host=FakeHost(), decryptor=lambda _: "")
    result = await c.search_git_history(query="x")
    assert isinstance(result, ToolError)
    assert "decrypted connector credential is empty" in result.error


# --------------------------------------------------------------------- host errors


@pytest.mark.parametrize(
    "status,fragment",
    [
        (401, "rejected the credential"),
        (403, "rejected the credential"),
        (404, "returned 404"),
        (422, "rejected the search query"),
        (429, "rate-limited"),
        (500, "HTTP 500"),
    ],
)
async def test_http_status_errors_map_to_a_safe_message(status: int, fragment: str) -> None:
    err = httpx.HTTPStatusError(
        "boom",
        request=httpx.Request("GET", "https://api.github.com/x"),
        response=httpx.Response(status),
    )
    result = await _connector(FakeHost(raises=err)).search_git_history(query="x")
    assert isinstance(result, ToolError)
    assert fragment in result.error


async def test_an_unimplemented_host_kind_is_a_tool_error_not_a_crash() -> None:
    client = httpx.AsyncClient(
        base_url="https://gitlab.example",
        transport=httpx.MockTransport(lambda _: httpx.Response(204)),
    )
    async with client:
        c = GitHistoryConnector(
            _cfg(base_url="https://gitlab.example"),
            settings=_settings(host_kind="gitlab"),
            client=client,
            decryptor=_identity,
        )
        result = await c.search_git_history(query="x")
    assert isinstance(result, ToolError)
    assert "gitlab" in result.error


async def test_a_transport_error_is_surfaced_by_type() -> None:
    err = httpx.ConnectError("no route")
    result = await _connector(FakeHost(raises=err)).search_git_history(query="x")
    assert isinstance(result, ToolError)
    assert result.error == "git host request failed: ConnectError"


# ------------------------------------------------------------------- happy evidence


async def test_no_matches_is_an_explicit_empty_success() -> None:
    result = await _connector(FakeHost()).search_git_history(query="nothing")
    assert isinstance(result, ToolSuccess)
    assert result.evidence == []
    assert result.found_evidence is False


async def test_commit_and_pr_and_churn_evidence_come_back_shaped_and_deduped() -> None:
    commit = CommitHit(
        repo="acme/store",
        sha="aaa111aaa111aaa111",
        message="Fix checkout coupon total",
        url="https://github.com/acme/store/commit/aaa111",
    )
    pr = PullRequestHit(
        repo="acme/store",
        number=214,
        title="Rework checkout coupons",
        body="move validation server-side",
        url="https://github.com/acme/store/pull/214",
    )
    host = FakeHost(
        commits=[commit, commit],  # dup collapses
        prs=[pr],
        records=[
            CommitRecord(
                sha="a",
                author="danalee",
                committed_at=_dt(20),
                additions=40,
                deletions=10,
                files_changed=3,
            ),
            CommitRecord(sha="b", author="priya", committed_at=_dt(10)),
        ],
    )
    result = await _connector(host).search_git_history(
        query="checkout coupon", path_hints=["/src/checkout/"]
    )
    assert isinstance(result, ToolSuccess)
    kinds = [(e.source, e.retrieved_by) for e in result.evidence]
    assert kinds == [("git", "search_git_history")] * 3
    refs = [e.ref for e in result.evidence]
    assert refs[0] == "https://github.com/acme/store/commit/aaa111"
    assert refs[1] == "https://github.com/acme/store/pull/214"
    assert refs[2].endswith("/acme/store/commits?path=src/checkout")
    assert "Fix checkout coupon total" in result.evidence[0].snippet
    assert result.evidence[1].snippet.startswith("acme/store#214: Rework checkout coupons")
    assert "move validation server-side" in result.evidence[1].snippet
    assert "2 commits" in result.evidence[2].snippet


async def test_evidence_refs_fall_back_when_the_host_gives_no_url() -> None:
    host = FakeHost(
        commits=[CommitHit(repo="acme/store", sha="deadbeef1234", message="msg", url="")],
        prs=[PullRequestHit(repo="acme/store", number=9, title="t", body="", url="")],
    )
    result = await _connector(host).search_git_history(query="x")
    assert isinstance(result, ToolSuccess)
    assert result.evidence[0].ref == "acme/store@deadbeef1234"
    assert result.evidence[1].ref == "acme/store#9"
    assert result.evidence[1].snippet == "acme/store#9: t"


async def test_path_hints_are_trimmed_deduped_and_capped() -> None:
    host = FakeHost()
    c = _connector(host)
    many = [f"/p{i}/" for i in range(20)] + ["/p0/", "  ", "/p1/"]
    await c.search_git_history(query="x", path_hints=many)
    churn_paths = [args[1] for name, args in host.calls if name == "churn"]
    assert churn_paths == [f"p{i}" for i in range(12)]


# --------------------------------------------------------------------- pure helpers


def test_identity_is_identity() -> None:
    assert _identity("abc") == "abc"


@pytest.mark.parametrize(
    "api,web",
    [
        ("https://api.github.com/", "https://github.com"),
        ("https://ghe.corp.example/api/v3", "https://ghe.corp.example"),
        ("https://git.example.com", "https://git.example.com"),
    ],
)
def test_web_base_url_maps_api_hosts(api: str, web: str) -> None:
    assert _web_base_url(api) == web


def test_load_decryptor_without_the_module_falls_back_to_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> Any:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(conn_mod.importlib, "import_module", missing)
    assert _load_decryptor()("plain") == "plain"


def test_load_decryptor_without_a_callable_falls_back_to_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conn_mod.importlib, "import_module", lambda _: object())
    assert _load_decryptor()("plain") == "plain"


def test_load_decryptor_uses_the_real_decrypt_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSecrets:
        @staticmethod
        def decrypt(value: str) -> str:
            return f"clear:{value}"

    monkeypatch.setattr(conn_mod.importlib, "import_module", lambda _: FakeSecrets)
    assert _load_decryptor()("c") == "clear:c"


# --------------------------------------------------------- connector-owned client


async def test_connector_builds_its_own_authenticated_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["accept"] = request.headers.get("accept")
        if request.url.path == "/search/commits":
            return httpx.Response(200, json=_load("search_commits_checkout.json"))
        return httpx.Response(200, json=_load("search_issues_empty.json"))

    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(conn_mod.httpx, "AsyncClient", factory)

    c = GitHistoryConnector(_cfg(), settings=_settings(), decryptor=lambda _: "s3cr3t")
    result = await c.search_git_history(query="checkout")

    assert isinstance(result, ToolSuccess)
    assert seen["auth"] == "Bearer s3cr3t"
    assert seen["accept"] == "application/vnd.github+json"
    assert result.evidence[0].snippet.startswith("acme/store@aaa111aaa111")


async def test_connector_runs_a_real_host_over_an_injected_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search/commits":
            return httpx.Response(200, json=_load("search_commits_empty.json"))
        if path == "/search/issues":
            return httpx.Response(200, json=_load("search_issues_checkout.json"))
        raise AssertionError(path)

    client = httpx.AsyncClient(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    )
    async with client:
        c = GitHistoryConnector(_cfg(), settings=_settings(), client=client, decryptor=_identity)
        result = await c.search_git_history(query="checkout")

    assert isinstance(result, ToolSuccess)
    assert [e.ref for e in result.evidence] == ["https://github.com/acme/store/pull/214"]


def _dt(day: int = 1) -> datetime:
    return datetime(2026, 8, day, tzinfo=UTC)
