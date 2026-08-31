"""Configuration comes from the environment, and only from there (§8.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from firsthand.config import Settings, get_settings


def test_defaults_point_at_the_local_compose_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir("/")
    settings = Settings()
    assert settings.database_url.endswith("/firsthand")
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.embedding_dimensions == 1536
    assert settings.state_ttl_seconds == 86_400
    assert settings.port == 8080


def test_every_setting_is_overridable_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir("/")
    monkeypatch.setenv("FIRSTHAND_DATABASE_URL", "postgresql://u:p@db:5432/x")
    monkeypatch.setenv("FIRSTHAND_REDIS_URL", "redis://cache:6379/2")
    monkeypatch.setenv("FIRSTHAND_EMBEDDING_DIMENSIONS", "768")
    monkeypatch.setenv("FIRSTHAND_PORT", "9000")

    settings = get_settings()
    assert settings.database_url == "postgresql://u:p@db:5432/x"
    assert settings.redis_url == "redis://cache:6379/2"
    assert settings.embedding_dimensions == 768
    assert settings.port == 9000


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FIRSTHAND_EMBEDDING_DIMENSIONS", "0"),
        ("FIRSTHAND_STATE_TTL_SECONDS", "0"),
        ("FIRSTHAND_PORT", "70000"),
    ],
)
def test_nonsense_values_fail_at_startup_not_at_first_use(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.chdir("/")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        get_settings()
