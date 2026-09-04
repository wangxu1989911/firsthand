"""The two shapes the docs retrieval pipeline moves around.

Neither is a §3 contract: they are internal to this connector. A ``DocPage`` is
what a provider hands back after an HTTP round trip; a ``Passage`` is one chunk
of one page, and a ``Passage`` is what becomes an ``Evidence`` snippet.
"""

from __future__ import annotations

from pydantic import Field

from firsthand.contracts.draft import Contract


class DocPage(Contract):
    """One design-doc page a provider retrieved.

    ``url`` is the followable reference an ``Evidence`` will point at, so it is
    never allowed to be empty; a provider that cannot produce one drops the page
    rather than emitting an uncitable hit.
    """

    title: str = Field(min_length=1)
    url: str = Field(min_length=1, description="Followable page URL — becomes Evidence.ref")
    text: str = Field(description="Plain-text body, markup already stripped")
    space: str | None = Field(default=None, description="Confluence space / Notion workspace name")


class Passage(Contract):
    """A single ranked chunk of a page.

    ``ordinal`` is the chunk's position within its page. It is carried so ties in
    the ranker break deterministically (by page URL, then ordinal) instead of on
    whatever order the provider happened to return.
    """

    page: DocPage
    text: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
