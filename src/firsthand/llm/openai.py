"""The real LLM client: an OpenAI-compatible HTTP provider (design doc §8.6).

This is the one place a network call leaves the container. It is never exercised
by a test — unit and integration suites inject :class:`RecordedLLM` — so its job
is to be small, explicit about retries, and honest when the provider misbehaves.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import ValidationError

from firsthand.config import Settings
from firsthand.llm.base import LLMError, StructuredT

#: Status codes worth a retry: rate limiting and transient upstream failures.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class OpenAILLM:
    """Structured chat + embeddings over an OpenAI-compatible REST API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        chat_model: str,
        embedding_model: str,
        timeout_seconds: float,
        max_retries: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("an LLM api key is required to build the real client")
        self._chat_model = chat_model
        self._embedding_model = embedding_model
        self._max_retries = max_retries
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )
        # Applied whether the client is ours or injected, so a test double sends
        # the same auth header the real path would.
        self._client.headers["Authorization"] = f"Bearer {api_key}"

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAILLM:
        """Build the client from environment-only configuration."""
        return cls(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            chat_model=settings.llm_chat_model,
            embedding_model=settings.llm_embedding_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    async def aclose(self) -> None:
        """Close the underlying client if this instance created it."""
        if self._owns_client:
            await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with a bounded retry on rate-limit and transient upstream errors."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(path, json=payload)
            except httpx.HTTPError as exc:  # timeout, connection reset, DNS, …
                last_exc = exc
            else:
                if response.status_code not in _RETRYABLE_STATUS:
                    if response.status_code >= 400:
                        raise LLMError(
                            f"{path} returned {response.status_code}: {response.text[:200]}"
                        )
                    body: dict[str, Any] = response.json()
                    return body
                last_exc = LLMError(f"{path} returned retryable {response.status_code}")
            if attempt < self._max_retries:
                await asyncio.sleep(0.5 * (2**attempt))
        raise LLMError(f"{path} failed after {self._max_retries + 1} attempts: {last_exc}")

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[StructuredT],
    ) -> StructuredT:
        body = await self._post(
            "/chat/completions",
            {
                "model": self._chat_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
        )
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected chat-completions shape: {body!r}") from exc
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"model did not return JSON: {content[:200]!r}") from exc
        try:
            return schema.model_validate(parsed)
        except ValidationError as exc:
            raise LLMError(f"model JSON did not match {schema.__name__}: {exc}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = await self._post(
            "/embeddings",
            {"model": self._embedding_model, "input": texts},
        )
        try:
            data = sorted(body["data"], key=lambda row: int(row["index"]))
            return [list(row["embedding"]) for row in data]
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMError(f"unexpected embeddings shape: {body!r}") from exc
