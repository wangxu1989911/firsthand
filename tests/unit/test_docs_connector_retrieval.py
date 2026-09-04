"""Chunking and ranking: deterministic, offline, no LLM."""

from __future__ import annotations

from firsthand.connectors.docs.models import DocPage, Passage
from firsthand.connectors.docs.retrieval import (
    Bm25Index,
    _split_long_paragraph,
    chunk_page,
    tokenize,
)


def _page(text: str, *, url: str = "https://docs.example.com/p", title: str = "P") -> DocPage:
    return DocPage(title=title, url=url, text=text)


def test_tokenize_lowercases_and_keeps_only_alphanumeric_runs() -> None:
    assert tokenize("Dark-Mode, please! (v2)") == ["dark", "mode", "please", "v2"]


def test_split_long_paragraph_packs_then_flushes() -> None:
    # Small budget: each sentence lands in its own chunk, and the trailing
    # ". " produces an empty segment that is skipped rather than chunked.
    tight = _split_long_paragraph("Alpha beta. Gamma delta. Epsilon. ", 12)
    assert tight == ["Alpha beta.", "Gamma delta.", "Epsilon."]

    # Roomier budget: adjacent short sentences pack into one chunk.
    packed = _split_long_paragraph("One. Two. Three.", 10)
    assert packed == ["One. Two.", "Three."]


def test_chunk_page_splits_on_paragraphs_and_drops_empty_blocks() -> None:
    page = _page("\n\nFirst paragraph here.\n\n   \n\nSecond paragraph here.")
    passages = chunk_page(page)
    assert [p.text for p in passages] == ["First paragraph here.", "Second paragraph here."]
    assert [p.ordinal for p in passages] == [0, 1]
    assert all(p.page is page for p in passages)


def test_chunk_page_falls_back_to_sentence_split_for_a_long_paragraph() -> None:
    long_paragraph = " ".join(f"Sentence number {n} about exports." for n in range(40))
    passages = chunk_page(_page(long_paragraph), max_chars=120)
    assert len(passages) > 1
    assert all(len(p.text) <= 120 for p in passages)
    # Every chunk is non-empty — Evidence.snippet is never allowed to be blank.
    assert all(p.text.strip() for p in passages)


def test_bm25_ranks_the_passage_that_shares_the_most_query_terms_first() -> None:
    passages = [
        Passage(
            page=_page("about billing invoices", url="https://d/a"),
            text="about billing invoices",
            ordinal=0,
        ),
        Passage(
            page=_page("dark mode theme toggle", url="https://d/b"),
            text="dark mode theme toggle",
            ordinal=1,
        ),
        Passage(
            page=_page("dark roast coffee notes", url="https://d/c"),
            text="dark roast coffee notes",
            ordinal=2,
        ),
    ]
    ranked = Bm25Index(passages).rank("dark mode theme", limit=5)
    assert [p.page.url for p in ranked] == ["https://d/b", "https://d/c"]


def test_bm25_drops_passages_that_share_no_term_with_the_query() -> None:
    passages = chunk_page(_page("Single sign-on through Okta and Azure AD."))
    assert Bm25Index(passages).rank("dark mode", limit=5) == []


def test_bm25_is_deterministic_on_ties_ordering_by_url_then_ordinal() -> None:
    same = "export issues to csv"
    passages = [
        Passage(page=_page(same, url="https://d/z"), text=same, ordinal=1),
        Passage(page=_page(same, url="https://d/z"), text=same, ordinal=0),
        Passage(page=_page(same, url="https://d/a"), text=same, ordinal=9),
    ]
    ranked = Bm25Index(passages).rank("export csv", limit=3)
    assert [(p.page.url, p.ordinal) for p in ranked] == [
        ("https://d/a", 9),
        ("https://d/z", 0),
        ("https://d/z", 1),
    ]


def test_bm25_handles_an_out_of_vocabulary_query_term() -> None:
    passages = chunk_page(_page("Bulk CSV export of issues."))
    ranked = Bm25Index(passages).rank("csv quokkazzz", limit=5)
    assert len(ranked) == 1


def test_bm25_dedupes_repeated_query_terms() -> None:
    passages = chunk_page(_page("dark mode is the request."))
    a = Bm25Index(passages).rank("dark dark dark mode", limit=5)
    b = Bm25Index(passages).rank("dark mode", limit=5)
    assert [p.text for p in a] == [p.text for p in b]


def test_bm25_on_an_empty_index_returns_nothing() -> None:
    index = Bm25Index([])
    assert index.rank("anything", limit=5) == []


def test_bm25_with_only_tokenless_passages_returns_nothing() -> None:
    passages = [Passage(page=_page("!!!"), text="!!! ???", ordinal=0)]
    assert Bm25Index(passages).rank("dark mode", limit=5) == []


def test_bm25_rejects_a_non_positive_limit() -> None:
    passages = chunk_page(_page("dark mode request"))
    assert Bm25Index(passages).rank("dark", limit=0) == []


def test_bm25_with_a_tokenless_query_returns_nothing() -> None:
    passages = chunk_page(_page("dark mode request"))
    assert Bm25Index(passages).rank("!!! ???", limit=5) == []
