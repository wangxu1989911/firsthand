"""The ``search_design_docs`` connector — design-doc passages as evidence (§5)."""

from firsthand.connectors.docs.connector import (
    DEFAULT_MAX_RESULTS,
    Decryptor,
    DesignDocsConnector,
)
from firsthand.connectors.docs.models import DocPage, Passage
from firsthand.connectors.docs.providers import (
    ConfluenceProvider,
    DocsProvider,
    FixtureProvider,
    build_confluence_client,
    strip_markup,
)
from firsthand.connectors.docs.retrieval import Bm25Index, chunk_page, tokenize

__all__ = [
    "DEFAULT_MAX_RESULTS",
    "Bm25Index",
    "ConfluenceProvider",
    "Decryptor",
    "DesignDocsConnector",
    "DocPage",
    "DocsProvider",
    "FixtureProvider",
    "Passage",
    "build_confluence_client",
    "chunk_page",
    "strip_markup",
    "tokenize",
]
