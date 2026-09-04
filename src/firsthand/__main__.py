"""``python -m firsthand`` — run the service with the configured host/port."""

from __future__ import annotations

from firsthand.config import get_settings


def main() -> None:
    """Serve the app under uvicorn, built per worker via the app factory."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "firsthand.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    main()
