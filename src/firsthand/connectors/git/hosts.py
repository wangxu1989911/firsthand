"""The HTTP seam: one :class:`GitHost` protocol, a real GitHub REST client, and
room for a GitLab sibling.

Everything above this file works in retrieved passages and aggregate counts.
Everything in it works in requests and JSON. Tests drive the real client through
an ``httpx.MockTransport`` fed by ``tests/fixtures/git/`` — no network (§8.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from firsthand.connectors.git.settings import HostKind

#: A single hostile or ambiguous request must not page forever. The call budget
#: is the primary bound; this is the backstop when the budget is generous.
MAX_COMMIT_PAGES = 10


class CallBudget:
    """A shared counter for outbound API calls within one connector invocation."""

    def __init__(self, limit: int) -> None:
        if limit <= 0:
            raise ValueError("call budget limit must be positive")
        self._limit = limit
        self._used = 0

    @property
    def used(self) -> int:
        """Calls spent so far."""
        return self._used

    @property
    def limit(self) -> int:
        """Ceiling this budget was created with."""
        return self._limit

    @property
    def exhausted(self) -> bool:
        """Whether the next :meth:`spend` will be refused."""
        return self._used >= self._limit

    def spend(self) -> bool:
        """Claim one call. Returns ``False`` (and claims nothing) when spent."""
        if self._used >= self._limit:
            return False
        self._used += 1
        return True


@dataclass(frozen=True, slots=True)
class CommitHit:
    """A commit whose message matched the query."""

    repo: str
    sha: str
    message: str
    url: str


@dataclass(frozen=True, slots=True)
class PullRequestHit:
    """A pull/merge request whose title or body matched the query."""

    repo: str
    number: int
    title: str
    body: str
    url: str


@dataclass(frozen=True, slots=True)
class CommitRecord:
    """One commit touching a path, for churn/ownership aggregation.

    ``additions``/``deletions``/``files_changed`` are ``None`` when per-commit
    detail was not fetched (budget or sample limit) — the aggregator reports a
    sampled count rather than pretending zero.
    """

    sha: str
    author: str
    committed_at: datetime
    additions: int | None = None
    deletions: int | None = None
    files_changed: int | None = None


class GitHost(Protocol):
    """What the connector needs from a Git host, and nothing more."""

    async def search_commits(self, repo: str, query: str, limit: int) -> list[CommitHit]:
        """Commits in ``repo`` whose message matches ``query``, newest first."""
        ...

    async def search_pull_requests(self, repo: str, query: str, limit: int) -> list[PullRequestHit]:
        """PRs in ``repo`` whose title/body matches ``query``, newest first."""
        ...

    async def commits_touching(
        self, repo: str, path: str, since: datetime, *, detail_limit: int
    ) -> tuple[list[CommitRecord], bool]:
        """Commits touching ``path`` since ``since``; flag is ``True`` if capped."""
        ...


def _clip(text: str, limit: int = 600) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class GitHubHost:
    """GitHub REST v3 client. One method per thing the connector asks for."""

    def __init__(self, client: httpx.AsyncClient, budget: CallBudget) -> None:
        self._client = client
        self._budget = budget

    async def _get(self, url: str, params: dict[str, str | int]) -> httpx.Response | None:
        """One budgeted GET. ``None`` means the budget is spent; stop asking."""
        if not self._budget.spend():
            return None
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        return response

    async def search_commits(self, repo: str, query: str, limit: int) -> list[CommitHit]:
        response = await self._get(
            "/search/commits",
            {"q": f"{query} repo:{repo}", "per_page": limit, "sort": "committer-date"},
        )
        if response is None:
            return []
        hits: list[CommitHit] = []
        for item in response.json().get("items", []):
            message = _clip(str(item.get("commit", {}).get("message", "")))
            if not message:
                continue
            hits.append(
                CommitHit(
                    repo=str(item.get("repository", {}).get("full_name", repo)),
                    sha=str(item["sha"]),
                    message=message,
                    url=str(item.get("html_url", "")),
                )
            )
        return hits

    async def search_pull_requests(self, repo: str, query: str, limit: int) -> list[PullRequestHit]:
        response = await self._get(
            "/search/issues",
            {"q": f"{query} repo:{repo} type:pr", "per_page": limit, "sort": "updated"},
        )
        if response is None:
            return []
        hits: list[PullRequestHit] = []
        for item in response.json().get("items", []):
            title = _clip(str(item.get("title", "")), 300)
            body = _clip(str(item.get("body") or ""))
            passage = f"{title}\n\n{body}".strip() if body else title
            if not passage:
                continue
            hits.append(
                PullRequestHit(
                    repo=repo,
                    number=int(item["number"]),
                    title=title,
                    body=body,
                    url=str(item.get("html_url", "")),
                )
            )
        return hits

    async def commits_touching(
        self, repo: str, path: str, since: datetime, *, detail_limit: int
    ) -> tuple[list[CommitRecord], bool]:
        records: list[CommitRecord] = []
        detailed = 0
        capped = False
        for page in range(1, MAX_COMMIT_PAGES + 1):
            listing = await self._get(
                f"/repos/{repo}/commits",
                {
                    "path": path,
                    "since": since.isoformat(),
                    "per_page": 100,
                    "page": page,
                },
            )
            if listing is None:
                capped = True
                break
            batch = listing.json()
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                sha = str(item["sha"])
                add = dele = files = None
                if detailed < detail_limit:
                    detail = await self._get(f"/repos/{repo}/commits/{sha}", {})
                    if detail is None:
                        capped = True
                    else:
                        detailed += 1
                        payload = detail.json()
                        stats = payload.get("stats") or {}
                        add = int(stats.get("additions", 0))
                        dele = int(stats.get("deletions", 0))
                        files = len(payload.get("files") or [])
                records.append(
                    CommitRecord(
                        sha=sha,
                        author=_author_of(item),
                        committed_at=_parsed_date(item),
                        additions=add,
                        deletions=dele,
                        files_changed=files,
                    )
                )
            if len(batch) < 100:
                break
            if page == MAX_COMMIT_PAGES or self._budget.exhausted:
                capped = True
        return records, capped


def _author_of(item: dict[str, object]) -> str:
    account = item.get("author")
    if isinstance(account, dict) and account.get("login"):
        return str(account["login"])
    commit = item.get("commit")
    if isinstance(commit, dict):
        author = commit.get("author")
        if isinstance(author, dict) and author.get("name"):
            return str(author["name"])
    return "unknown"


#: Sentinel for a commit whose timestamp the host did not report — old enough to
#: never win a "most recent" comparison, and obviously not a real date.
UNKNOWN_DATE = datetime.fromtimestamp(0, tz=UTC)


def _parsed_date(item: dict[str, object]) -> datetime:
    commit = item.get("commit")
    raw = ""
    if isinstance(commit, dict):
        author = commit.get("author")
        if isinstance(author, dict):
            raw = str(author.get("date", ""))
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return UNKNOWN_DATE


def make_host(kind: HostKind, client: httpx.AsyncClient, budget: CallBudget) -> GitHost:
    """Build the host client for ``kind``. GitLab is a declared, unbuilt seam."""
    if kind == "github":
        return GitHubHost(client, budget)
    raise NotImplementedError(f"git host {kind!r} is a declared seam, not yet implemented")
