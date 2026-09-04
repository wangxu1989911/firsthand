"""The LLM seam: the one dependency that has to leave the box (design doc §8.6).

Everything the orchestrator needs from a model is behind :class:`LLMClient` —
structured chat completion and embeddings. The real provider client lives in
``openai.py``; every test injects the recorded-fixture client from
``fixtures.py`` instead, so no unit or integration test needs a network or a
key (§8.6).
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

#: Structured-output calls are parameterised by the Pydantic model the caller
#: wants back. The client's job is to make the model return JSON and to hand
#: back a validated instance — never a raw dict.
StructuredT = TypeVar("StructuredT", bound=BaseModel)


class ChatMessage(BaseModel):
    """One turn in a chat prompt. ``content`` is always redacted text (§1)."""

    model_config = {"extra": "forbid"}

    role: str
    content: str


class LLMError(RuntimeError):
    """The model call failed after exhausting retries, or returned unusable output.

    Raised rather than swallowed: a scoring or classification step that cannot
    reach the model must surface, not quietly return a default the orchestrator
    would treat as a real judgement.
    """


@runtime_checkable
class LLMClient(Protocol):
    """What the orchestrator is written against. Two methods, no provider detail."""

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[StructuredT],
    ) -> StructuredT:
        """Return an instance of ``schema``, validated from the model's JSON reply.

        ``system`` and ``user`` carry only redacted text. Raises :class:`LLMError`
        if the call fails or the reply does not validate against ``schema``.
        """
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed each string, returning one vector per input, in order.

        The vectors are whatever width the configured embedding model emits; the
        caller is responsible for matching that to the vector store's dimension.
        """
        ...
