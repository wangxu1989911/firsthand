"""Storage contracts and their default implementations (design doc §3, §8.6).

The orchestrator only ever sees :class:`VectorStore` and :class:`StateStore`.
Swapping Postgres for Qdrant, or Redis for DynamoDB, means writing one class
against these interfaces — not touching orchestrator code.
"""

from firsthand.storage.base import Match, StateStore, VectorStore
from firsthand.storage.postgres_vector import PostgresVectorStore
from firsthand.storage.redis_state import RedisStateStore

__all__ = [
    "Match",
    "PostgresVectorStore",
    "RedisStateStore",
    "StateStore",
    "VectorStore",
]
