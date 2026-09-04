"""``search_git_history`` — the Git evidence connector.

Given keywords and optional path hints from the orchestrator, it returns a list
of :class:`~firsthand.contracts.Evidence`:

* commit messages and PR titles/bodies that match the query, each with a
  followable ``ref`` (a commit sha or ``owner/repo#NN``); and
* churn/ownership passages for the hinted paths, so the orchestrator can weigh
  effort — numbers computed here, judgement made there.

Nothing matched is an explicit ``ToolSuccess(evidence=[])``, never a hedge (§5).
"""

from __future__ import annotations

import importlib
import logging
import re
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx

from firsthand.connectors.git.churn import churn_evidence, summarize
from firsthand.connectors.git.hosts import (
    CallBudget,
    CommitHit,
    GitHost,
    PullRequestHit,
    make_host,
)
from firsthand.connectors.git.settings import GitConnectorSettings, is_valid_repo
from firsthand.contracts import (
    ConnectorConfig,
    Evidence,
    ToolCall,
    ToolError,
    ToolResult,
    ToolSuccess,
)

logger = logging.getLogger(__name__)

_TOOL = "search_git_history"
_MAX_QUERY_CHARS = 256
_MAX_PATH_HINTS = 12


class GitConnectorError(Exception):
    """A configuration problem that stops the connector before any request."""


def _identity(value: str) -> str:
    return value


def _load_decryptor() -> Callable[[str], str]:
    """Resolve ``firsthand.secrets.decrypt`` if Phase 2 has shipped it yet.

    Imported dynamically so this connector neither hard-depends on a module that
    may not exist nor trips mypy over a missing stub. Until it lands, the
    credential is used as-is — noted loudly, and in the PR.
    """
    try:
        module = importlib.import_module("firsthand.secrets")
    except ModuleNotFoundError:
        logger.warning(
            "firsthand.secrets.decrypt not available yet; using the connector "
            "credential as plaintext. This must not reach production."
        )
        return _identity
    decrypt = getattr(module, "decrypt", None)
    if not callable(decrypt):
        logger.warning("firsthand.secrets has no callable decrypt(); using credential as plaintext")
        return _identity
    return cast("Callable[[str], str]", decrypt)


def _web_base_url(api_base_url: str) -> str:
    """Best-effort map from an API base URL to the human/browser base URL."""
    base = api_base_url.rstrip("/")
    base = re.sub(r"/api/v3$", "", base)
    base = base.replace("//api.github.com", "//github.com")
    return base


class GitHistoryConnector:
    """Runs ``search_git_history`` against a Git host, returning evidence only."""

    def __init__(
        self,
        config: ConnectorConfig,
        *,
        settings: GitConnectorSettings | None = None,
        client: httpx.AsyncClient | None = None,
        host: GitHost | None = None,
        decryptor: Callable[[str], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if config.type != "git":
            raise GitConnectorError(f"expected a git ConnectorConfig, got {config.type!r}")
        self._config = config
        self._settings = settings or GitConnectorSettings()
        self._client = client
        self._host = host
        self._decryptor = decryptor
        self._now = now or (lambda: datetime.now(UTC))

    async def run(self, call: ToolCall) -> ToolResult:
        """Dispatch a :class:`ToolCall`, validating its args before any request."""
        if call.name != _TOOL:
            return ToolError(error=f"git connector received tool {call.name!r}, not {_TOOL!r}")
        raw_query = call.args.get("query", "")
        if not isinstance(raw_query, str):
            return ToolError(error="'query' must be a string")
        hints, hint_error = _coerce_hints(call.args.get("path_hints", []))
        if hint_error is not None:
            return ToolError(error=hint_error)
        return await self.search_git_history(query=raw_query, path_hints=hints)

    async def search_git_history(self, *, query: str, path_hints: Sequence[str] = ()) -> ToolResult:
        """Search commits/PRs and measure churn for ``path_hints``."""
        query = query.strip()
        if not query:
            return ToolError(error="'query' must not be empty")
        if len(query) > _MAX_QUERY_CHARS:
            return ToolError(error=f"'query' exceeds {_MAX_QUERY_CHARS} characters")

        repos = self._settings.repo_list
        if not repos:
            return ToolError(error="no repositories configured (set FIRSTHAND_GIT_REPOS)")
        bad = [repo for repo in repos if not is_valid_repo(repo)]
        if bad:
            return ToolError(error=f"not a valid owner/repo slug: {bad[0]!r}")

        hints = _clean_hints(path_hints)

        try:
            token = self._resolve_token()
        except GitConnectorError as exc:
            return ToolError(error=str(exc))

        budget = CallBudget(self._settings.max_api_calls)
        since = self._now() - timedelta(days=self._settings.churn_window_days)
        web_base = _web_base_url(self._config.base_url)

        try:
            if self._host is not None:
                evidence = await self._collect(self._host, repos, hints, query, since, web_base)
            else:
                async with self._open_client(token) as client:
                    host = make_host(self._settings.host_kind, client, budget)
                    evidence = await self._collect(host, repos, hints, query, since, web_base)
        except NotImplementedError as exc:
            return ToolError(error=str(exc))
        except httpx.HTTPStatusError as exc:
            return ToolError(error=_describe_status(exc))
        except httpx.HTTPError as exc:
            return ToolError(error=f"git host request failed: {type(exc).__name__}")

        return ToolSuccess(evidence=_dedupe(evidence))

    async def _collect(
        self,
        host: GitHost,
        repos: list[str],
        hints: list[str],
        query: str,
        since: datetime,
        web_base: str,
    ) -> list[Evidence]:
        limit = self._settings.max_results_per_repo
        evidence: list[Evidence] = []
        for repo in repos:
            for commit in await host.search_commits(repo, query, limit):
                evidence.append(_commit_evidence(commit))
            for pull in await host.search_pull_requests(repo, query, limit):
                evidence.append(_pr_evidence(pull))
        for repo in repos:
            for path in hints:
                records, capped = await host.commits_touching(
                    repo, path, since, detail_limit=self._settings.churn_detail_limit
                )
                stats = summarize(
                    repo,
                    path,
                    records,
                    window_days=self._settings.churn_window_days,
                    capped=capped,
                    web_base_url=web_base,
                )
                if stats is not None:
                    evidence.append(churn_evidence(stats))
        return evidence

    def _resolve_token(self) -> str:
        credential = self._config.credential
        if not credential:
            raise GitConnectorError("connector credential is empty")
        decrypt = self._decryptor or _load_decryptor()
        try:
            token = decrypt(credential)
        except Exception as exc:  # a decrypt of any kind failing is a config failure
            raise GitConnectorError(
                f"could not decrypt connector credential: {type(exc).__name__}"
            ) from exc
        if not token:
            raise GitConnectorError("decrypted connector credential is empty")
        return token

    @asynccontextmanager
    async def _open_client(self, token: str) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "firsthand-git-connector",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
        }
        async with httpx.AsyncClient(
            base_url=self._config.base_url,
            headers=headers,
            timeout=self._settings.request_timeout_seconds,
        ) as client:
            yield client


def _coerce_hints(value: Any) -> tuple[list[str], str | None]:
    if isinstance(value, str):
        return [value], None
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return list(value), None
        return [], "'path_hints' must be a list of strings"
    return [], "'path_hints' must be a string or a list of strings"


def _clean_hints(hints: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for hint in hints:
        trimmed = hint.strip().strip("/")
        if trimmed and trimmed not in seen:
            seen.add(trimmed)
            cleaned.append(trimmed)
        if len(cleaned) >= _MAX_PATH_HINTS:
            break
    return cleaned


def _commit_evidence(hit: CommitHit) -> Evidence:
    return Evidence(
        source="git",
        ref=hit.url or f"{hit.repo}@{hit.sha}",
        snippet=f"{hit.repo}@{hit.sha[:12]}: {hit.message}",
        retrieved_by=_TOOL,
    )


def _pr_evidence(hit: PullRequestHit) -> Evidence:
    return Evidence(
        source="git",
        ref=hit.url or f"{hit.repo}#{hit.number}",
        snippet=f"{hit.repo}#{hit.number}: {hit.title}" + (f"\n\n{hit.body}" if hit.body else ""),
        retrieved_by=_TOOL,
    )


def _describe_status(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status in (401, 403):
        return "git host rejected the credential (401/403)"
    if status == 404:
        return "git host returned 404 for a configured repository"
    if status == 422:
        return "git host rejected the search query (422)"
    if status == 429:
        return "git host rate-limited the connector (429)"
    return f"git host returned HTTP {status}"


def _dedupe(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, str]] = set()
    unique: list[Evidence] = []
    for item in evidence:
        key = (item.ref, item.snippet)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
