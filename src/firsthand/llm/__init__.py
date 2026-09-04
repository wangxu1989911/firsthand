"""The LLM seam and its two implementations (design doc §8.6).

``LLMClient`` is the interface the orchestrator depends on. ``OpenAILLM`` is the
real provider client; ``RecordedLLM`` replays fixtures and is the only client
any test uses.
"""

from firsthand.llm.base import ChatMessage, LLMClient, LLMError, StructuredT
from firsthand.llm.fixtures import (
    FixtureMissError,
    RecordedLLM,
    embedding_key,
    structured_key,
)
from firsthand.llm.openai import OpenAILLM

__all__ = [
    "ChatMessage",
    "FixtureMissError",
    "LLMClient",
    "LLMError",
    "OpenAILLM",
    "RecordedLLM",
    "StructuredT",
    "embedding_key",
    "structured_key",
]
