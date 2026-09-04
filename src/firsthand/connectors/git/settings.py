"""Process-wide configuration for the Git connector — environment only (§8.3).

Where the connector *points* (API base URL, credential) is per-connector and
arrives on a :class:`~firsthand.contracts.ConnectorConfig`. Everything that is
the same for every request the process makes — which repositories to search, how
far back to measure churn, how many outbound calls a single lookup may spend —
lives here and is read from ``FIRSTHAND_GIT_*`` variables.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

HostKind = Literal["github", "gitlab"]

#: ``owner/repo`` (GitHub) or ``group/subgroup/project`` (GitLab) — the segments
#: browsers and both APIs accept, nothing that could smuggle a path traversal or
#: a query string into a URL we build.
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")


def parse_repo_list(raw: str) -> list[str]:
    """Split a comma- or whitespace-separated repo list, preserving order.

    Deduplicates while keeping the first occurrence so a doubled entry in the
    environment does not double every outbound call.
    """
    seen: set[str] = set()
    repos: list[str] = []
    for chunk in raw.replace(",", " ").split():
        if chunk not in seen:
            seen.add(chunk)
            repos.append(chunk)
    return repos


def is_valid_repo(repo: str) -> bool:
    """Whether ``repo`` is a safe ``owner/name`` slug to interpolate into a URL."""
    if not _REPO_RE.match(repo):
        return False
    return all(segment not in {".", ".."} for segment in repo.split("/"))


class GitConnectorSettings(BaseSettings):
    """Knobs shared by every ``search_git_history`` invocation in this process."""

    model_config = SettingsConfigDict(env_prefix="FIRSTHAND_GIT_", extra="ignore")

    #: Comma/whitespace separated ``owner/repo`` slugs to search.
    repos: str = ""

    #: Which host dialect to speak. ``gitlab`` is a declared seam, not yet wired.
    host_kind: HostKind = "github"

    #: Churn/ownership window. "Recent" is a config decision, not a magic number.
    churn_window_days: int = Field(default=90, gt=0, le=365)

    #: Per-commit detail (line/file counts) costs one API call each, so it is
    #: sampled up to this many commits per path. 0 disables line/file detail
    #: and leaves commit-count + author signals only.
    churn_detail_limit: int = Field(default=25, ge=0)

    #: Hard ceiling on outbound API calls for a single ``search_git_history``
    #: call — the same reflex as ``MAX_TOOL_CALLS`` one level up (§7).
    max_api_calls: int = Field(default=20, gt=0, le=200)

    #: How many search hits to keep per repo, per category (commits, PRs).
    max_results_per_repo: int = Field(default=10, gt=0, le=50)

    #: Page size for the commit-history walk; GitHub caps this at 100.
    commit_page_size: int = Field(default=100, gt=0, le=100)

    #: Timeout applied to each outbound request when the connector owns the
    #: client (an injected client keeps its own).
    request_timeout_seconds: float = Field(default=10.0, gt=0)

    @property
    def repo_list(self) -> list[str]:
        """Configured repositories, in order, de-duplicated."""
        return parse_repo_list(self.repos)
