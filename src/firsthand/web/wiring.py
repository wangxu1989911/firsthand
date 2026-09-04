"""Bolt the Phase 2 web chat and admin area onto the Phase 0 skeleton.

``create_app`` calls :func:`attach_phase2` once. It wraps (does not replace) the
skeleton's lifespan so the original startup still runs, then builds the
Redis-backed stores the routers need, picks the orchestrator (Phase 1's real
loop when an LLM key is set, the deterministic stub otherwise), and bootstraps
the first admin account.
"""

from __future__ import annotations

import logging
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
from firsthand.connectors.jira import JiraConnector, jira_connector_from_config
from firsthand.contracts import ConnectorConfig
from firsthand.llm import OpenAILLM
from firsthand.orchestrator import OrchestratorDeps, ToolRegistry
from firsthand.web.intake import Orchestrator
from firsthand.web.log import ConversationLog
from firsthand.web.orchestrator import LoopOrchestrator, StubOrchestrator, unconfigured_jira
from firsthand.web.routes import router as web_router
from firsthand.web.service import ChatService

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


def _resolve_jira(config: ConnectorConfig | None) -> JiraConnector:
    """Build the Jira connector from its stored config, or a no-op stand-in.

    A missing config is the ordinary first-run state. A *present but unusable*
    one (bad ciphertext, wrong credential shape) must not take the public chat
    down with it, so it degrades the same way — logged, and every Jira call
    fails cleanly.
    """
    if config is None:
        return unconfigured_jira()
    try:
        return jira_connector_from_config(config)
    except Exception:
        logger.exception("stored Jira connector config is unusable; running without Jira")
        return unconfigured_jira()


async def _build_orchestrator(
    app: FastAPI, settings: Settings, connectors: ConnectorConfigStore
) -> Orchestrator:
    """Phase 1's loop when there is an LLM key to run it, the stub otherwise."""
    if not settings.llm_api_key:
        logger.warning("FIRSTHAND_LLM_API_KEY is unset; the web chat runs on the stub orchestrator")
        return StubOrchestrator()

    resources = app.state.resources
    deps = OrchestratorDeps(
        llm=OpenAILLM.from_settings(settings),
        vector_store=resources.vector_store,
        state_store=resources.state_store,
        tools=ToolRegistry(jira=_resolve_jira(await connectors.get("jira"))),
        project_key=settings.jira_project_key,
        state_ttl_seconds=settings.state_ttl_seconds,
    )
    return LoopOrchestrator(deps)


async def _install_stores(app: FastAPI, settings: Settings) -> None:
    """Construct the process-wide stores and stash them on ``app.state``."""
    resources = app.state.resources
    redis = resources.redis

    log = ConversationLog(redis, ttl_seconds=settings.state_ttl_seconds)
    index = DraftIndex(redis)
    connectors = ConnectorConfigStore(redis)
    orchestrator = await _build_orchestrator(app, settings, connectors)
    app.state.orchestrator = orchestrator
    app.state.chat_service = ChatService(
        resources.state_store,
        orchestrator,
        log,
        index,
        state_ttl_seconds=settings.state_ttl_seconds,
    )
    app.state.draft_index = index
    app.state.connectors = connectors
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
            await _install_stores(app, settings)
            await bootstrap_admin(app.state.admin_users)
            try:
                yield
            finally:
                closer = getattr(app.state.orchestrator, "aclose", None)
                if closer is not None:
                    await closer()

    app.router.lifespan_context = lifespan
    app.add_exception_handler(AdminRedirectError, admin_redirect_handler)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(web_router)
    app.include_router(admin_router)
