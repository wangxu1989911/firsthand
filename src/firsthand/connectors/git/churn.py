"""Turn a list of commits touching a path into difficulty *signals* — never a
score.

The connector reports how much a region of the tree has been churning and how
concentrated its ownership is, as an :class:`~firsthand.contracts.Evidence`
passage the orchestrator reads. Deciding what "42 commits, 2 authors" means for
RICE effort is the orchestrator's call, not this module's (§3, CLAUDE.md §2).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from firsthand.connectors.git.hosts import UNKNOWN_DATE, CommitRecord
from firsthand.contracts import Evidence


@dataclass(frozen=True, slots=True)
class ChurnStats:
    """Aggregate activity for one path over the configured window."""

    repo: str
    path: str
    window_days: int
    commit_count: int
    distinct_authors: int
    top_author: str
    top_author_share: float
    additions: int
    deletions: int
    files_changed: int
    detail_sample: int
    last_commit_at: datetime | None
    capped: bool
    url: str

    @property
    def has_line_detail(self) -> bool:
        """Whether any per-commit line/file detail was fetched."""
        return self.detail_sample > 0


def summarize(
    repo: str,
    path: str,
    records: list[CommitRecord],
    *,
    window_days: int,
    capped: bool,
    web_base_url: str,
) -> ChurnStats | None:
    """Fold ``records`` into a :class:`ChurnStats`, or ``None`` if there were none."""
    if not records:
        return None
    authors = Counter(record.author for record in records)
    top_author, top_count = authors.most_common(1)[0]
    detailed = [r for r in records if r.additions is not None]
    additions = sum(r.additions or 0 for r in detailed)
    deletions = sum(r.deletions or 0 for r in detailed)
    files_changed = sum(r.files_changed or 0 for r in detailed)
    newest = max(record.committed_at for record in records)
    return ChurnStats(
        repo=repo,
        path=path,
        window_days=window_days,
        commit_count=len(records),
        distinct_authors=len(authors),
        top_author=top_author,
        top_author_share=top_count / len(records),
        additions=additions,
        deletions=deletions,
        files_changed=files_changed,
        detail_sample=len(detailed),
        last_commit_at=None if newest == UNKNOWN_DATE else newest,
        capped=capped,
        url=f"{web_base_url.rstrip('/')}/{repo}/commits?path={path}",
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def churn_evidence(stats: ChurnStats) -> Evidence:
    """Render one :class:`ChurnStats` as a git-sourced evidence passage."""
    commits = ("at least " if stats.capped else "") + _plural(stats.commit_count, "commit")
    parts = [
        f"{stats.repo}/{stats.path} — {commits}",
    ]
    if stats.has_line_detail:
        scope = (
            "across all of them"
            if stats.detail_sample >= stats.commit_count
            else f"sampled from {stats.detail_sample}"
        )
        parts.append(
            f"+{stats.additions}/-{stats.deletions} lines over "
            f"{_plural(stats.files_changed, 'file')} changed ({scope})"
        )
    share = round(stats.top_author_share * 100)
    parts.append(
        f"{_plural(stats.distinct_authors, 'author')}, "
        f"top author {stats.top_author!r} made {share}% of commits"
    )
    parts.append(f"in the last {stats.window_days}d")
    if stats.last_commit_at is not None:
        parts.append(f"most recent {stats.last_commit_at.date().isoformat()}")
    return Evidence(
        source="git",
        ref=stats.url,
        snippet="; ".join(parts) + ".",
        retrieved_by="search_git_history",
    )
