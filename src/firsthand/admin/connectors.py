"""Redis-backed persistence for :class:`ConnectorConfig` (design doc §3, §8.7).

This store never encrypts or decrypts: it round-trips whatever ``credential``
string it is handed. Encryption is the caller's job (see
:func:`firsthand.admin.service.save_connector`), which keeps the ciphertext the
only form that ever reaches storage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from firsthand.contracts import ConnectorConfig, ConnectorType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis

__all__ = ["CONNECTOR_TYPES", "ConnectorConfigStore"]

#: The connector kinds an operator can configure, in display order.
CONNECTOR_TYPES: tuple[ConnectorType, ...] = get_args(ConnectorType)

_CONNECTOR_PREFIX = "firsthand:connector"


class ConnectorConfigStore:
    """One :class:`ConnectorConfig` per connector type."""

    def __init__(self, redis: Redis, *, prefix: str = _CONNECTOR_PREFIX) -> None:
        self._redis = redis
        self._prefix = prefix

    def _key(self, connector_type: ConnectorType) -> str:
        return f"{self._prefix}:{connector_type}"

    async def get(self, connector_type: ConnectorType) -> ConnectorConfig | None:
        """Return the stored config for one type, or ``None``."""
        raw = await self._redis.get(self._key(connector_type))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return ConnectorConfig.model_validate_json(raw)

    async def put(self, config: ConnectorConfig) -> None:
        """Insert or replace the config for ``config.type``."""
        await self._redis.set(self._key(config.type), config.model_dump_json())

    async def delete(self, connector_type: ConnectorType) -> None:
        """Remove the config for one type; a no-op if there is none."""
        await self._redis.delete(self._key(connector_type))

    async def list(self) -> list[ConnectorConfig]:
        """Every configured connector, in :data:`CONNECTOR_TYPES` order."""
        configs: list[ConnectorConfig] = []
        for connector_type in CONNECTOR_TYPES:
            config = await self.get(connector_type)
            if config is not None:
                configs.append(config)
        return configs
