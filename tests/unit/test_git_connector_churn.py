"""Churn/ownership aggregation renders as evidence text — never a score."""

from __future__ import annotations

from datetime import UTC, datetime

from firsthand.connectors.git.churn import ChurnStats, churn_evidence, summarize
from firsthand.connectors.git.hosts import UNKNOWN_DATE, CommitRecord


def _rec(sha: str, author: str, *, day: int, detail: bool) -> CommitRecord:
    return CommitRecord(
        sha=sha,
        author=author,
        committed_at=datetime(2026, 8, day, tzinfo=UTC),
        additions=10 if detail else None,
        deletions=4 if detail else None,
        files_changed=3 if detail else None,
    )


def test_summarize_returns_none_for_no_commits() -> None:
    assert summarize("acme/store", "x", [], window_days=90, capped=False, web_base_url="w") is None


def test_summarize_folds_counts_authors_and_recency() -> None:
    records = [
        _rec("a", "danalee", day=20, detail=True),
        _rec("b", "danalee", day=18, detail=True),
        _rec("c", "priya", day=10, detail=False),
    ]
    stats = summarize(
        "acme/store",
        "src/checkout/",
        records,
        window_days=90,
        capped=False,
        web_base_url="https://github.com/",
    )
    assert stats is not None
    assert stats.commit_count == 3
    assert stats.distinct_authors == 2
    assert stats.top_author == "danalee"
    assert stats.top_author_share == 2 / 3
    assert (stats.additions, stats.deletions, stats.files_changed) == (20, 8, 6)
    assert stats.detail_sample == 2
    assert stats.last_commit_at == datetime(2026, 8, 20, tzinfo=UTC)
    assert stats.url == "https://github.com/acme/store/commits?path=src/checkout/"


def test_summarize_drops_recency_when_every_date_is_unknown() -> None:
    records = [
        CommitRecord(sha="a", author="x", committed_at=UNKNOWN_DATE),
        CommitRecord(sha="b", author="y", committed_at=UNKNOWN_DATE),
    ]
    stats = summarize("acme/store", "x", records, window_days=30, capped=False, web_base_url="w")
    assert stats is not None
    assert stats.last_commit_at is None
    assert stats.has_line_detail is False


def test_evidence_reads_as_a_passage_with_full_detail() -> None:
    stats = ChurnStats(
        repo="acme/store",
        path="src/checkout/",
        window_days=90,
        commit_count=42,
        distinct_authors=2,
        top_author="danalee",
        top_author_share=0.75,
        additions=380,
        deletions=120,
        files_changed=44,
        detail_sample=42,
        last_commit_at=datetime(2026, 8, 20, tzinfo=UTC),
        capped=False,
        url="https://github.com/acme/store/commits?path=src/checkout/",
    )
    ev = churn_evidence(stats)
    assert ev.source == "git"
    assert ev.retrieved_by == "search_git_history"
    assert ev.ref.endswith("path=src/checkout/")
    assert "42 commits" in ev.snippet
    assert "+380/-120 lines over 44 files changed (across all of them)" in ev.snippet
    assert "2 authors, top author 'danalee' made 75% of commits" in ev.snippet
    assert "most recent 2026-08-20" in ev.snippet


def test_evidence_marks_capped_counts_and_sampled_detail_and_singulars() -> None:
    stats = ChurnStats(
        repo="acme/store",
        path="f.py",
        window_days=7,
        commit_count=1,
        distinct_authors=1,
        top_author="solo",
        top_author_share=1.0,
        additions=5,
        deletions=1,
        files_changed=1,
        detail_sample=1,
        last_commit_at=None,
        capped=True,
        url="u",
    )
    snippet = churn_evidence(stats).snippet
    assert snippet.startswith("acme/store/f.py — at least 1 commit;")
    assert "1 file changed (across all of them)" in snippet
    assert "1 author," in snippet
    assert "most recent" not in snippet


def test_evidence_reports_a_partial_detail_sample() -> None:
    stats = ChurnStats(
        repo="acme/store",
        path="d/",
        window_days=90,
        commit_count=40,
        distinct_authors=3,
        top_author="a",
        top_author_share=0.5,
        additions=100,
        deletions=50,
        files_changed=20,
        detail_sample=10,
        last_commit_at=None,
        capped=False,
        url="u",
    )
    assert "(sampled from 10)" in churn_evidence(stats).snippet


def test_evidence_omits_line_detail_when_none_was_fetched() -> None:
    stats = ChurnStats(
        repo="acme/store",
        path="d/",
        window_days=90,
        commit_count=5,
        distinct_authors=1,
        top_author="a",
        top_author_share=1.0,
        additions=0,
        deletions=0,
        files_changed=0,
        detail_sample=0,
        last_commit_at=None,
        capped=False,
        url="u",
    )
    snippet = churn_evidence(stats).snippet
    assert "lines over" not in snippet
    assert "5 commits" in snippet
