"""Configuration comes from the environment, and only from there (§8.3)."""

from __future__ import annotations

import pathlib

import pytest
from pydantic import ValidationError

from firsthand.config import Settings, get_settings


def test_defaults_point_at_the_local_compose_stack() -> None:
    settings = Settings()
    assert settings.database_url.endswith("/firsthand")
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.embedding_dimensions == 1536
    assert settings.state_ttl_seconds == 86_400
    assert settings.port == 8080


def test_every_setting_is_overridable_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        get_settings()


def test_a_dotenv_file_in_the_cwd_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Config comes from the environment only — never from the working directory."""
    (tmp_path / ".env").write_text("FIRSTHAND_DATABASE_URL=postgresql://leaked@evil/db\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FIRSTHAND_DATABASE_URL", raising=False)

    assert "evil" not in get_settings().database_url


def test_a_misspelled_log_level_fails_at_startup_naming_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WARN is an ordinary spelling; uvicorn only takes `warning` and dies on a KeyError."""
    monkeypatch.setenv("FIRSTHAND_LOG_LEVEL", "WARN")
    with pytest.raises(ValidationError):
        get_settings()


def test_pool_bounds_must_be_consistent(monkeypatch: pytest.MonkeyPatch) -> None:
    """psycopg raises this deep inside from_settings; catching it here names the knob."""
    monkeypatch.setenv("FIRSTHAND_POOL_MIN_SIZE", "20")
    monkeypatch.setenv("FIRSTHAND_POOL_MAX_SIZE", "10")
    with pytest.raises(ValidationError, match="pool_min_size"):
        get_settings()


def test_an_embedding_width_past_pgvectors_ceiling_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """vector(20000) would fail at CREATE TABLE, after the process looked healthy."""
    monkeypatch.setenv("FIRSTHAND_EMBEDDING_DIMENSIONS", "20000")
    with pytest.raises(ValidationError):
        get_settings()


def test_a_width_above_the_hnsw_limit_is_still_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """3072 is text-embedding-3-large's width: indexable or not, it must boot."""
    monkeypatch.setenv("FIRSTHAND_EMBEDDING_DIMENSIONS", "3072")
    assert get_settings().embedding_dimensions == 3072
