"""Driver-level fakes, so unit tests cover the stores without a container.

The real thing is covered too — see tests/integration, which runs the same
operations against the Postgres and Redis containers from docker-compose.yml.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any


class FakeCursor:
    def __init__(self, rows: Sequence[tuple[Any, ...]]) -> None:
        self._rows = list(rows)

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class FakeConnection:
    def __init__(self, rows: Sequence[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.executed.append((" ".join(sql.split()), params))
        return FakeCursor(self.rows)


class FakePool:
    """Stands in for psycopg_pool.AsyncConnectionPool."""

    def __init__(self, rows: Sequence[tuple[Any, ...]] = (), fail_on_connect: bool = False) -> None:
        self.conn = FakeConnection(rows)
        self.opened = False
        self.closed = False
        self.fail_on_connect = fail_on_connect
        self.connection_timeouts: list[float | None] = []

    @asynccontextmanager
    async def connection(self, timeout: float | None = None) -> AsyncIterator[FakeConnection]:
        self.connection_timeouts.append(timeout)
        if self.fail_on_connect:
            raise RuntimeError("connection refused")
        yield self.conn

    async def open(self, wait: bool = False) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    @property
    def statements(self) -> list[str]:
        return [sql for sql, _ in self.conn.executed]


class FakeRedis:
    """Stands in for redis.asyncio.Redis.

    Covers the string, set, and list operations Phase 2's Redis-backed stores
    use. ``raw_as_bytes`` mirrors a client built without ``decode_responses``.
    """

    def __init__(self, *, raw_as_bytes: bool = False, fail_ping: bool = False) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}
        self.sets: dict[str, set[str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.expirations: dict[str, int] = {}
        self.raw_as_bytes = raw_as_bytes
        self.fail_ping = fail_ping
        self.closed = False

    def _maybe_bytes(self, value: str) -> str | bytes:
        return value.encode("utf-8") if self.raw_as_bytes else value

    async def get(self, key: str) -> str | bytes | None:
        entry = self.store.get(key)
        if entry is None:
            return None
        return self._maybe_bytes(entry[0])

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = (value, ex)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)
            self.sets.pop(key, None)
            self.lists.pop(key, None)

    async def sadd(self, key: str, *members: str) -> None:
        self.sets.setdefault(key, set()).update(members)

    async def smembers(self, key: str) -> set[str | bytes]:
        return {self._maybe_bytes(m) for m in self.sets.get(key, set())}

    async def rpush(self, key: str, *values: str) -> None:
        self.lists.setdefault(key, []).extend(values)

    async def lrange(self, key: str, start: int, end: int) -> list[str | bytes]:
        items = self.lists.get(key, [])
        stop = None if end == -1 else end + 1
        return [self._maybe_bytes(v) for v in items[start:stop]]

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations[key] = ttl

    async def ping(self) -> bool:
        if self.fail_ping:
            raise RuntimeError("redis down")
        return True

    async def aclose(self) -> None:
        self.closed = True
