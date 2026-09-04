"""Configuration — environment variables only (design doc §8.3).

Nothing cloud-specific is ever baked into the image: the same container runs on
a laptop, Cloud Run, or Fargate, and only its environment differs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: pgvector's own ceiling for the `vector` column type.
MAX_EMBEDDING_DIMENSIONS = 16_000

LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "TRACE"]


class Settings(BaseSettings):
    """Everything the process needs to know, read from the environment."""

    # Deliberately no env_file: reading a .env would make configuration depend
    # on the process working directory and give a developer different results
    # than CI. §8.3 means the environment, and nothing else.
    model_config = SettingsConfigDict(env_prefix="FIRSTHAND_", extra="ignore")

    database_url: str = "postgresql://firsthand:firsthand@localhost:5432/firsthand"
    redis_url: str = "redis://localhost:6379/0"

    embedding_dimensions: int = Field(default=1536, gt=0, le=MAX_EMBEDDING_DIMENSIONS)
    state_ttl_seconds: int = Field(default=86_400, gt=0)

    pool_min_size: int = Field(default=1, ge=0)
    pool_max_size: int = Field(default=10, gt=0)

    #: Redis has no default timeout of its own; without one a half-open socket
    #: hangs the readiness probe forever instead of failing it.
    redis_timeout_seconds: float = Field(default=5.0, gt=0)

    # The one call that leaves the box (§8.6). Tests never read these — every
    # unit and integration test injects a recorded-fixture client instead — so
    # an empty api_key is a valid state right up until the real client is built.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_chat_model: str = "gpt-4o-mini"
    llm_embedding_model: str = "text-embedding-3-small"
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)

    host: str = "0.0.0.0"
    port: int = Field(default=8080, gt=0, le=65_535)

    # Phase 2 — web chat + admin area.
    #: Master key for authenticated encryption of connector credentials (§8.7)
    #: and for signing admin session cookies. It lives only in the environment;
    #: an empty value is allowed so the public chat can boot without it, but any
    #: admin or connector-credential path raises until it is set.
    secret_key: str = ""
    #: How long an admin login session stays valid before re-authentication.
    admin_session_ttl_seconds: int = Field(default=43_200, gt=0)
    #: Optional path to a JSON eval report; the dashboard renders it when present.
    eval_report_path: str = ""
    # A bare `str` here means an ordinary misspelling (WARN for WARNING) passes
    # validation and then dies inside uvicorn as a bare KeyError, in a container
    # with nothing to inspect. Fail at startup, naming the value.
    log_level: LogLevel = "INFO"

    @model_validator(mode="after")
    def _pool_bounds_are_consistent(self) -> Settings:
        """psycopg raises this deep in from_settings; catching it here names the knob."""
        if self.pool_min_size > self.pool_max_size:
            raise ValueError(
                f"pool_min_size ({self.pool_min_size}) must not exceed"
                f" pool_max_size ({self.pool_max_size})"
            )
        return self


def get_settings() -> Settings:
    """Read settings fresh from the environment."""
    return Settings()
