"""Admin area: login, forced password rotation, dashboard, connector config.

Every page here needs a signed, Redis-backed session (see
:mod:`firsthand.auth.sessions`). Unauthenticated access to any ``/admin`` page
redirects to the login form; an account still on its bootstrap password is
redirected to the change-password form until it rotates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from firsthand.admin.connectors import CONNECTOR_TYPES, ConnectorConfigStore
from firsthand.admin.dashboard import (
    REVIEWABLE_STATES,
    DraftIndex,
    load_drafts,
    read_eval_report,
)
from firsthand.admin.service import ReviewDecision, review_draft, save_connector
from firsthand.auth import AdminSession, AdminSessionStore, AdminUserStore, verify_password
from firsthand.auth.passwords import hash_password
from firsthand.contracts import MAX_CLARIFICATION_ROUNDS, ConnectorType
from firsthand.storage import StateStore

ADMIN_COOKIE = "firsthand_admin"
_MIN_PASSWORD_LENGTH = 12
_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_SEE_OTHER = status.HTTP_303_SEE_OTHER

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminRedirectError(Exception):
    """Raised inside a dependency to bounce the browser to another admin page."""

    def __init__(self, location: str) -> None:
        super().__init__(location)
        self.location = location


async def admin_redirect_handler(request: Request, exc: Exception) -> Response:
    """Turn an :class:`AdminRedirectError` into a 303."""
    return RedirectResponse(cast(AdminRedirectError, exc).location, status_code=_SEE_OTHER)


# --------------------------------------------------------------------------- deps


def _users(request: Request) -> AdminUserStore:
    store: AdminUserStore = request.app.state.admin_users
    return store


def _sessions(request: Request) -> AdminSessionStore:
    store: AdminSessionStore | None = request.app.state.admin_sessions
    if store is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the admin area requires FIRSTHAND_SECRET_KEY to be set",
        )
    return store


def _connectors(request: Request) -> ConnectorConfigStore:
    store: ConnectorConfigStore = request.app.state.connectors
    return store


def _draft_index(request: Request) -> DraftIndex:
    index: DraftIndex = request.app.state.draft_index
    return index


def _state(request: Request) -> StateStore:
    store: StateStore = request.app.state.resources.state_store
    return store


def _eval_report_path(request: Request) -> str:
    path: str = request.app.state.eval_report_path
    return path


def _session_ttl(request: Request) -> int:
    ttl: int = request.app.state.admin_session_ttl_seconds
    return ttl


async def optional_session(
    request: Request,
    sessions: Annotated[AdminSessionStore, Depends(_sessions)],
) -> AdminSession | None:
    """The current login session, or ``None`` when signed out."""
    return await sessions.resolve(request.cookies.get(ADMIN_COOKIE))


async def require_admin(
    session: Annotated[AdminSession | None, Depends(optional_session)],
) -> AdminSession:
    """A valid session, or a redirect to the login form."""
    if session is None:
        raise AdminRedirectError("/admin/login")
    return session


async def require_rotated_password(
    session: Annotated[AdminSession, Depends(require_admin)],
    users: Annotated[AdminUserStore, Depends(_users)],
) -> AdminSession:
    """As :func:`require_admin`, but also bounce accounts still on the bootstrap
    password to the change-password form."""
    user = await users.get(session.username)
    if user is None:
        raise AdminRedirectError("/admin/login")
    if user.must_change_password:
        raise AdminRedirectError("/admin/password")
    return session


SessionDep = Annotated[AdminSession, Depends(require_admin)]
RotatedDep = Annotated[AdminSession, Depends(require_rotated_password)]


def _set_cookie(response: Response, value: str, ttl: int) -> None:
    response.set_cookie(
        ADMIN_COOKIE, value, httponly=True, samesite="lax", max_age=ttl, path="/admin"
    )


# ------------------------------------------------------------------------- auth


@router.get("/", include_in_schema=False)
async def admin_root() -> RedirectResponse:
    return RedirectResponse("/admin/dashboard", status_code=_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse)
async def login_form(
    request: Request,
    session: Annotated[AdminSession | None, Depends(optional_session)],
) -> Response:
    if session is not None:
        return RedirectResponse("/admin/dashboard", status_code=_SEE_OTHER)
    return _TEMPLATES.TemplateResponse(request, "login.html", {})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    users: Annotated[AdminUserStore, Depends(_users)],
    sessions: Annotated[AdminSessionStore, Depends(_sessions)],
    ttl: Annotated[int, Depends(_session_ttl)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    user = await users.get(username)
    if user is None or not verify_password(user.password_hash, password):
        return _TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": "Wrong username or password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    cookie = await sessions.create(user.username)
    target = "/admin/password" if user.must_change_password else "/admin/dashboard"
    response = RedirectResponse(target, status_code=_SEE_OTHER)
    _set_cookie(response, cookie, ttl)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    sessions: Annotated[AdminSessionStore, Depends(_sessions)],
) -> RedirectResponse:
    await sessions.destroy(request.cookies.get(ADMIN_COOKIE))
    response = RedirectResponse("/admin/login", status_code=_SEE_OTHER)
    response.delete_cookie(ADMIN_COOKIE, path="/admin")
    return response


@router.get("/password", response_class=HTMLResponse)
async def password_form(
    request: Request,
    session: SessionDep,
    users: Annotated[AdminUserStore, Depends(_users)],
) -> Response:
    user = await users.get(session.username)
    must_change = user is not None and user.must_change_password
    return _TEMPLATES.TemplateResponse(
        request, "password.html", {"username": session.username, "must_change": must_change}
    )


@router.post("/password", response_class=HTMLResponse)
async def password_submit(
    request: Request,
    session: SessionDep,
    users: Annotated[AdminUserStore, Depends(_users)],
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
) -> Response:
    user = await users.get(session.username)
    error: str | None = None
    if user is None or not verify_password(user.password_hash, current_password):
        error = "Current password is wrong."
    elif new_password != confirm_password:
        error = "The new passwords do not match."
    elif len(new_password) < _MIN_PASSWORD_LENGTH:
        error = f"Use at least {_MIN_PASSWORD_LENGTH} characters."

    if error is not None or user is None:
        return _TEMPLATES.TemplateResponse(
            request,
            "password.html",
            {"username": session.username, "must_change": True, "error": error},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    await users.put(
        user.model_copy(
            update={"password_hash": hash_password(new_password), "must_change_password": False}
        )
    )
    return RedirectResponse("/admin/dashboard", status_code=_SEE_OTHER)


# -------------------------------------------------------------------- dashboard


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: RotatedDep,
    index: Annotated[DraftIndex, Depends(_draft_index)],
    state: Annotated[StateStore, Depends(_state)],
    eval_path: Annotated[str, Depends(_eval_report_path)],
) -> Response:
    summaries = await load_drafts(index, state)
    return _TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {
            "username": session.username,
            "summaries": summaries,
            "eval_report": read_eval_report(eval_path),
        },
    )


@router.get("/dashboard/drafts/{session_id}", response_class=HTMLResponse)
async def draft_detail(
    request: Request,
    session: RotatedDep,
    session_id: str,
    state: Annotated[StateStore, Depends(_state)],
) -> Response:
    draft = await state.get(session_id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such request")
    return _TEMPLATES.TemplateResponse(
        request,
        "draft.html",
        {
            "username": session.username,
            "session_id": session_id,
            "draft": draft,
            "reviewable": draft.status in REVIEWABLE_STATES,
            "max_rounds": MAX_CLARIFICATION_ROUNDS,
        },
    )


@router.post("/dashboard/drafts/{session_id}/review")
async def draft_review(
    session: RotatedDep,
    session_id: str,
    state: Annotated[StateStore, Depends(_state)],
    decision: Annotated[str, Form()],
) -> RedirectResponse:
    if decision not in ("approve", "reject"):
        raise HTTPException(422, "decision must be approve or reject")
    try:
        await review_draft(
            state, session_id, cast(ReviewDecision, decision), reviewer=session.username
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return RedirectResponse("/admin/dashboard", status_code=_SEE_OTHER)


# ----------------------------------------------------------------------- config


@router.get("/config", response_class=HTMLResponse)
async def config_page(
    request: Request,
    session: RotatedDep,
    connectors: Annotated[ConnectorConfigStore, Depends(_connectors)],
) -> Response:
    return _TEMPLATES.TemplateResponse(
        request,
        "config.html",
        {
            "username": session.username,
            "connectors": await connectors.list(),
            "connector_types": CONNECTOR_TYPES,
        },
    )


def _require_connector_type(value: str) -> ConnectorType:
    if value not in CONNECTOR_TYPES:
        raise HTTPException(422, "unknown connector type")
    return value


@router.post("/config")
async def config_save(
    session: RotatedDep,
    connectors: Annotated[ConnectorConfigStore, Depends(_connectors)],
    connector_type: Annotated[str, Form()],
    base_url: Annotated[str, Form()],
    credential: Annotated[str, Form()] = "",
    enabled: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    await save_connector(
        connectors,
        connector_type=_require_connector_type(connector_type),
        base_url=base_url,
        credential=credential,
        enabled=enabled is not None,
        updated_by=session.username,
    )
    return RedirectResponse("/admin/config", status_code=_SEE_OTHER)


@router.post("/config/{connector_type}/delete")
async def config_delete(
    session: RotatedDep,
    connectors: Annotated[ConnectorConfigStore, Depends(_connectors)],
    connector_type: str,
) -> RedirectResponse:
    await connectors.delete(_require_connector_type(connector_type))
    return RedirectResponse("/admin/config", status_code=_SEE_OTHER)
