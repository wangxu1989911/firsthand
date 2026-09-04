"""The admin user store and first-boot bootstrap (design doc §8.7).

Records are held in Redis beside the other Phase 2 state rather than in process
memory. Passwords are argon2id hashes; the plaintext only ever exists in the
one WARNING log line the bootstrap emits.
"""

from __future__ import annotations

import logging
import secrets
import string
from typing import TYPE_CHECKING

from firsthand.auth.passwords import hash_password
from firsthand.contracts import AdminUser

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis

__all__ = ["AdminUserStore", "bootstrap_admin"]

logger = logging.getLogger(__name__)

_USER_PREFIX = "firsthand:admin:user"
_USER_INDEX = "firsthand:admin:users"
_BOOTSTRAP_USERNAME = "admin"
_BOOTSTRAP_PASSWORD_LENGTH = 20


class AdminUserStore:
    """CRUD for :class:`AdminUser` records, keyed by username."""

    def __init__(
        self, redis: Redis, *, prefix: str = _USER_PREFIX, index: str = _USER_INDEX
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._index = index

    def _key(self, username: str) -> str:
        return f"{self._prefix}:{username}"

    async def get(self, username: str) -> AdminUser | None:
        """Return the stored user, or ``None`` when there is none."""
        raw = await self._redis.get(self._key(username))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return AdminUser.model_validate_json(raw)

    async def put(self, user: AdminUser) -> None:
        """Insert or replace a user."""
        await self._redis.set(self._key(user.username), user.model_dump_json())
        await self._redis.sadd(self._index, user.username)

    async def any_exists(self) -> bool:
        """Whether at least one admin account has been created."""
        return bool(await self._redis.smembers(self._index))


async def bootstrap_admin(store: AdminUserStore) -> str | None:
    """Create the first-boot ``admin`` account if no admin exists yet.

    Returns the generated plaintext password the one time it creates the
    account (also logged once at WARNING), or ``None`` when an admin already
    exists and nothing was done.
    """
    if await store.any_exists():
        return None
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(_BOOTSTRAP_PASSWORD_LENGTH))
    await store.put(
        AdminUser(
            username=_BOOTSTRAP_USERNAME,
            password_hash=hash_password(password),
            must_change_password=True,
        )
    )
    logger.warning(
        "Bootstrapped admin account %r with a temporary password: %s — "
        "you must change it on first login",
        _BOOTSTRAP_USERNAME,
        password,
    )
    return password
