"""Admin and connector configuration shapes (design doc §3, §8.7)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from firsthand.contracts.draft import Contract

ConnectorType = Literal["jira", "git", "docs"]


def _now() -> datetime:
    return datetime.now(UTC)


class AdminUser(Contract):
    """An operator of the dashboard and configuration pages.

    ``password_hash`` is argon2id output — the plaintext is never stored, and
    the first-run account carries ``must_change_password`` until it is rotated.
    """

    username: str = Field(min_length=1)
    password_hash: str = Field(min_length=1)
    must_change_password: bool = False
    created_at: datetime = Field(default_factory=_now)


class ConnectorConfig(Contract):
    """Where a connector points and the credential it uses.

    ``credential`` is always ciphertext at rest: it is encrypted with a master
    key held only in an environment variable, never in the database (§8.7).
    """

    type: ConnectorType
    base_url: str = Field(min_length=1)
    credential: str = Field(repr=False, description="Encrypted at rest — never a plaintext token")
    enabled: bool = True
    updated_by: str = Field(min_length=1)
    updated_at: datetime = Field(default_factory=_now)
