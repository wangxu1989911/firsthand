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
    """Stands in for redis.asyncio.Redis."""

    def __init__(self, *, raw_as_bytes: bool = False, fail_ping: bool = False) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}
        self.raw_as_bytes = raw_as_bytes
        self.fail_ping = fail_ping
        self.closed = False

    async def get(self, key: str) -> str | bytes | None:
        entry = self.store.get(key)
        if entry is None:
            return None
        value = entry[0]
        return value.encode("utf-8") if self.raw_as_bytes else value

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = (value, ex)

    async def ping(self) -> bool:
        if self.fail_ping:
            raise RuntimeError("redis down")
        return True

    async def aclose(self) -> None:
        self.closed = True
