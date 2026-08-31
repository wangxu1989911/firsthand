"""Configuration — environment variables only (design doc §8.3).

Nothing cloud-specific is ever baked into the image: the same container runs on
a laptop, Cloud Run, or Fargate, and only its environment differs.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything the process needs to know, read from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="FIRSTHAND_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://firsthand:firsthand@localhost:5432/firsthand"
    redis_url: str = "redis://localhost:6379/0"

    embedding_dimensions: int = Field(default=1536, gt=0)
    state_ttl_seconds: int = Field(default=86_400, gt=0)

    pool_min_size: int = Field(default=1, ge=0)
    pool_max_size: int = Field(default=10, gt=0)

    host: str = "0.0.0.0"
    port: int = Field(default=8080, gt=0, le=65_535)
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Read settings fresh from the environment."""
    return Settings()
