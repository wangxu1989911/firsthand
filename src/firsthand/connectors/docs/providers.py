"""The provider seam: where design-doc content is fetched from.

``DocsProvider`` is the whole contract the connector depends on — hand it a
query, get back pages. ``ConfluenceProvider`` is the real HTTP implementation;
``FixtureProvider`` loads pages from disk so unit and offline integration tests
never touch a network (§8.6). A Notion provider slots in at the same seam and is
tracked as follow-up work.
"""

from __future__ import annotations

import html
import os
import pathlib
import re
from typing import Protocol

import httpx

from firsthand.connectors.docs.models import DocPage

#: Per-request ceiling for the real HTTP path. A design-doc search wants the top
#: handful of pages, not a crawl.
DEFAULT_PAGE_LIMIT = 25

#: Total timeout for one provider HTTP request. The connector maps a timeout to
#: a ``ToolError`` rather than letting it stall the six-call budget (§7).
DEFAULT_TIMEOUT_SECONDS = 10.0

_BLOCK_END = re.compile(r"(?i)</(?:p|div|h[1-6]|li|tr|blockquote)>|<br\s*/?>")
_TAG = re.compile(r"<[^>]+>")


class DocsProvider(Protocol):
    """Retrieves candidate pages for a query. Implementations do no ranking."""

    async def fetch(self, query: str, *, limit: int) -> list[DocPage]:
        """Return candidate pages; ``[]`` when nothing matches."""
        ...

    async def aclose(self) -> None:
        """Release any owned network resources."""
        ...


def strip_markup(markup: str) -> str:
    """Confluence storage format (XHTML) down to plain text, breaks preserved."""
    with_breaks = _BLOCK_END.sub("\n\n", markup)
    return html.unescape(_TAG.sub("", with_breaks)).strip()


def _escape_cql(value: str) -> str:
    """Escape a user string for a double-quoted CQL literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_confluence_client(base_url: str, credential: str, timeout: float) -> httpx.AsyncClient:
    """A client pointed at a Confluence site root.

    ``credential`` is ``email:api_token`` for Confluence Cloud (HTTP Basic) or a
    bare personal-access token for Server/Data Center (bearer).
    """
    headers = {"Accept": "application/json"}
    auth: httpx.Auth | None = None
    if ":" in credential:
        email, _, token = credential.partition(":")
        auth = httpx.BasicAuth(email, token)
    else:
        headers["Authorization"] = f"Bearer {credential}"
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"), headers=headers, auth=auth, timeout=timeout
    )


def _nested_str(source: object, *keys: str) -> str:
    """Walk a chain of dict keys, returning ``""`` the moment the path breaks."""
    current = source
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current) if isinstance(current, str) else ""


def _page_from_confluence(item: dict[str, object], base: str) -> DocPage | None:
    """Map one Confluence search result, or ``None`` if it cannot be cited."""
    title = _nested_str(item, "title").strip()
    webui = _nested_str(item, "_links", "webui")
    if not title or not webui:
        return None
    url = f"{base.rstrip('/')}{webui}" if webui.startswith("/") else webui
    text = strip_markup(_nested_str(item, "body", "storage", "value"))
    space = _nested_str(item, "space", "name") or None
    return DocPage(title=title, url=url, text=text, space=space)


class ConfluenceProvider:
    """Reads pages from the Confluence Content Search API over HTTPS."""

    def __init__(
        self,
        *,
        base_url: str,
        credential: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        page_limit: int = DEFAULT_PAGE_LIMIT,
    ) -> None:
        self._client = client or build_confluence_client(base_url, credential, timeout)
        self._page_limit = page_limit

    async def fetch(self, query: str, *, limit: int) -> list[DocPage]:
        params: dict[str, str | int] = {
            "cql": f'type=page AND text ~ "{_escape_cql(query)}"',
            "expand": "body.storage,space",
            "limit": max(1, min(limit, self._page_limit)),
        }
        response = await self._client.get("/wiki/rest/api/content/search", params=params)
        response.raise_for_status()
        payload = response.json()

        links = payload.get("_links") or {}
        base = str(links.get("base") or self._client.base_url)
        pages: list[DocPage] = []
        for item in payload.get("results") or []:
            page = _page_from_confluence(item, base)
            if page is not None:
                pages.append(page)
        return pages[:limit]

    async def aclose(self) -> None:
        await self._client.aclose()


class FixtureProvider:
    """Serves pages loaded from JSON on disk. Ignores the query — the ranker filters."""

    def __init__(self, pages: list[DocPage]) -> None:
        self._pages = list(pages)

    @classmethod
    def from_directory(cls, path: str | os.PathLike[str]) -> FixtureProvider:
        directory = pathlib.Path(path)
        pages = [
            DocPage.model_validate_json(file.read_text(encoding="utf-8"))
            for file in sorted(directory.glob("*.json"))
        ]
        return cls(pages)

    async def fetch(self, query: str, *, limit: int) -> list[DocPage]:
        return list(self._pages)

    async def aclose(self) -> None:
        return None
