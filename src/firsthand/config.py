"""Configuration — environment variables only (design doc §8.3).

Nothing cloud-specific is ever baked into the image: the same container runs on
a laptop, Cloud Run, or Fargate, and only its environment differs.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything the process needs to know, read from the environment."""

    # Deliberately no env_file: reading a .env would make configuration depend
    # on the process working directory and give a developer different results
    # than CI. §8.3 means the environment, and nothing else.
    model_config = SettingsConfigDict(env_prefix="FIRSTHAND_", extra="ignore")

    database_url: str = "postgresql://firsthand:firsthand@localhost:5432/firsthand"
    redis_url: str = "redis://localhost:6379/0"

    embedding_dimensions: int = Field(default=1536, gt=0)
    state_ttl_seconds: int = Field(default=86_400, gt=0)

    pool_min_size: int = Field(default=1, ge=0)
    pool_max_size: int = Field(default=10, gt=0)

    #: Redis has no default timeout of its own; without one a half-open socket
    #: hangs the readiness probe forever instead of failing it.
    redis_timeout_seconds: float = Field(default=5.0, gt=0)

    host: str = "0.0.0.0"
    port: int = Field(default=8080, gt=0, le=65_535)
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Read settings fresh from the environment."""
    return Settings()
