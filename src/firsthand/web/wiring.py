"""Bolt the Phase 2 web chat and admin area onto the Phase 0 skeleton.

``create_app`` calls :func:`attach_phase2` once. It wraps (does not replace) the
skeleton's lifespan so the original startup still runs, then builds the
Redis-backed stores the routers need and bootstraps the first admin account.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from firsthand.admin.connectors import ConnectorConfigStore
from firsthand.admin.dashboard import DraftIndex
from firsthand.admin.routes import AdminRedirectError, admin_redirect_handler
from firsthand.admin.routes import router as admin_router
from firsthand.auth import AdminSessionStore, AdminUserStore, CookieSigner, bootstrap_admin
from firsthand.config import Settings
from firsthand.web.log import ConversationLog
from firsthand.web.orchestrator import StubOrchestrator
from firsthand.web.routes import router as web_router
from firsthand.web.service import ChatService

_STATIC_DIR = Path(__file__).parent / "static"


def _install_stores(app: FastAPI, settings: Settings) -> None:
    """Construct the process-wide stores and stash them on ``app.state``."""
    resources = app.state.resources
    redis = resources.redis

    log = ConversationLog(redis, ttl_seconds=settings.state_ttl_seconds)
    index = DraftIndex(redis)
    app.state.chat_service = ChatService(
        resources.state_store,
        StubOrchestrator(),
        log,
        index,
        state_ttl_seconds=settings.state_ttl_seconds,
    )
    app.state.draft_index = index
    app.state.connectors = ConnectorConfigStore(redis)
    app.state.admin_users = AdminUserStore(redis)
    app.state.eval_report_path = settings.eval_report_path
    app.state.admin_session_ttl_seconds = settings.admin_session_ttl_seconds
    # The admin area needs the master key to sign session cookies; without it the
    # public chat still runs and every admin route answers 503.
    app.state.admin_sessions = (
        AdminSessionStore(
            redis,
            CookieSigner(settings.secret_key),
            ttl_seconds=settings.admin_session_ttl_seconds,
        )
        if settings.secret_key
        else None
    )


def attach_phase2(app: FastAPI, settings: Settings) -> None:
    """Wrap the lifespan, mount static assets, and include the Phase 2 routers."""
    skeleton_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with skeleton_lifespan(app):
            _install_stores(app, settings)
            await bootstrap_admin(app.state.admin_users)
            yield

    app.router.lifespan_context = lifespan
    app.add_exception_handler(AdminRedirectError, admin_redirect_handler)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(web_router)
    app.include_router(admin_router)
