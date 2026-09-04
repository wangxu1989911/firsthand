"""How the Jira connector talks to Jira — one thin seam over HTTP.

The connector is written against :class:`JiraTransport` so tests replay recorded
JSON (``fake.py``) and never open a socket. ``JiraHTTPTransport`` is the real
path: Jira Cloud REST v3, basic auth with an API token.
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

import httpx


class JiraTransportError(RuntimeError):
    """A transport-level failure (network, auth, 5xx). The connector turns this
    into a ``ToolError`` rather than letting it escape."""


class JiraTransport(Protocol):
    """The two calls the connector needs."""

    async def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET ``path`` with query ``params``, returning parsed JSON."""
        ...

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST ``payload`` as JSON to ``path``, returning parsed JSON."""
        ...


class JiraHTTPTransport:
    """Real Jira Cloud transport. Never exercised by a test (§8.6)."""

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        api_token: str,
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode("ascii")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )
        # Set on the client whether we made it or it was injected, so a test
        # double still carries the auth the real path would send.
        self._client.headers["Authorization"] = f"Basic {token}"
        self._client.headers["Accept"] = "application/json"

    async def aclose(self) -> None:
        """Close the client if this instance created it."""
        if self._owns_client:
            await self._client.aclose()

    async def _json(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise JiraTransportError(
                f"{response.request.method} {response.request.url.path} -> "
                f"{response.status_code}: {response.text[:200]}"
            )
        body: dict[str, Any] = response.json()
        return body

    async def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise JiraTransportError(f"GET {path} failed: {exc}") from exc
        return await self._json(response)

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise JiraTransportError(f"POST {path} failed: {exc}") from exc
        return await self._json(response)
