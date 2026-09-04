"""A recorded-fixture LLM client — the only one any test is allowed to use.

Tests must be deterministic and offline (§8.6), so instead of calling a provider
they replay responses keyed by a stable hash of the exact prompt. A prompt with
no recorded response is a hard error, never a silent default: an un-recorded
call in a test means the test would have hit the network in production.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from firsthand.llm.base import LLMError, StructuredT


class FixtureMissError(LLMError):
    """No recorded response matches this prompt or text."""


def _digest(*parts: str) -> str:
    """A stable key over the parts that fully determine a response."""
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def structured_key(schema_name: str, system: str, user: str) -> str:
    """Key a structured-output response by target schema and both prompt halves."""
    return _digest("structured", schema_name, system, user)


def embedding_key(text: str) -> str:
    """Key an embedding by its exact input text."""
    return _digest("embedding", text)


class RecordedLLM:
    """Replays recorded ``structured`` and ``embed`` responses. Satisfies ``LLMClient``.

    Build it directly with dicts in a unit test, or from a JSON file
    (``{"completions": {...}, "embeddings": {...}}``) for the larger fixtures the
    orchestrator and eval suites share.
    """

    def __init__(
        self,
        *,
        completions: Mapping[str, Any] | None = None,
        embeddings: Mapping[str, list[float]] | None = None,
    ) -> None:
        self._completions: dict[str, Any] = dict(completions or {})
        self._embeddings: dict[str, list[float]] = {
            key: list(value) for key, value in (embeddings or {}).items()
        }
        #: Every prompt/text asked for, in order — lets a test assert what the
        #: orchestrator actually sent the model.
        self.structured_calls: list[tuple[str, str, str]] = []
        self.embed_calls: list[list[str]] = []

    @classmethod
    def from_file(cls, path: str | Path) -> RecordedLLM:
        """Load a shared fixture file."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            completions=payload.get("completions", {}),
            embeddings=payload.get("embeddings", {}),
        )

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[StructuredT],
    ) -> StructuredT:
        self.structured_calls.append((schema.__name__, system, user))
        key = structured_key(schema.__name__, system, user)
        try:
            recorded = self._completions[key]
        except KeyError:
            raise FixtureMissError(
                f"no recorded {schema.__name__} completion for key {key};"
                " record the response or fix the prompt"
            ) from None
        try:
            return schema.model_validate(recorded)
        except ValidationError as exc:  # a recorded blob that no longer fits the schema
            raise LLMError(
                f"recorded {schema.__name__} completion no longer validates: {exc}"
            ) from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        vectors: list[list[float]] = []
        for text in texts:
            key = embedding_key(text)
            try:
                vectors.append(list(self._embeddings[key]))
            except KeyError:
                raise FixtureMissError(
                    f"no recorded embedding for key {key}; record the vector or fix the text"
                ) from None
        return vectors
