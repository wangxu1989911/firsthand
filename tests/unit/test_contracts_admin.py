"""Admin and connector config: nothing sensitive is ever stored in the clear (§8.7)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from firsthand.contracts import AdminUser, ConnectorConfig


def test_first_run_admin_carries_the_forced_rotation_flag() -> None:
    user = AdminUser(
        username="admin", password_hash="$argon2id$v=19$...", must_change_password=True
    )
    assert user.must_change_password
    assert user.created_at.tzinfo is not None


def test_created_at_defaults_to_an_aware_utc_timestamp() -> None:
    before = datetime.now(UTC)
    user = AdminUser(username="admin", password_hash="hash")
    assert before <= user.created_at <= datetime.now(UTC)
    assert not user.must_change_password


def test_the_stored_credential_never_shows_up_in_a_repr() -> None:
    config = ConnectorConfig(
        type="jira",
        base_url="https://example.atlassian.net",
        credential="gAAAAAB-ciphertext",
        updated_by="admin",
    )
    assert "gAAAAAB-ciphertext" not in repr(config)
    assert config.enabled


def test_a_connector_needs_a_known_type_and_a_url() -> None:
    with pytest.raises(ValidationError):
        ConnectorConfig(type="sharepoint", base_url="https://x", credential="c", updated_by="admin")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ConnectorConfig(type="docs", base_url="", credential="c", updated_by="admin")


def test_an_admin_user_needs_a_username_and_a_hash() -> None:
    with pytest.raises(ValidationError):
        AdminUser(username="", password_hash="hash")
    with pytest.raises(ValidationError):
        AdminUser(username="admin", password_hash="")
