"""The Phase 0 skeleton service.

Deliberately thin: it proves the container, the pool, and the schema all come
up together. The web chat and admin area land on top of this in Phase 2.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from firsthand import __version__
from firsthand.config import Settings, get_settings
from firsthand.resources import AppResources


def create_app(
    settings: Settings | None = None,
    resources: AppResources | None = None,
) -> FastAPI:
    """Build the ASGI app. Tests inject ``resources``; production builds them."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.resources = resources or AppResources.from_settings(settings)
        # open() inside the try: a startup that fails partway still releases
        # whatever it managed to connect, instead of leaking it on a crash-loop.
        try:
            await app.state.resources.open()
            yield
        finally:
            await app.state.resources.close()

    app = FastAPI(
        title="Firsthand",
        version=__version__,
        summary="Catches duplicate and related feature requests before they're filed twice.",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness: the process is up. Says nothing about its dependencies."""
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Readiness: Postgres and Redis both answered."""
        checks = await app.state.resources.check()
        ready = all(value == "ok" for value in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready", "checks": checks},
        )

    return app
