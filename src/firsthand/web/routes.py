"""Public web-chat routes: a server-rendered page and a JSON turn endpoint.

No authentication — anyone can file a request. The only cookie is an opaque
session id that scopes the draft in the ``StateStore``; it carries no
privileges, so it is not signed.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from firsthand.web.service import ChatService

SESSION_COOKIE = "firsthand_session"
_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

router = APIRouter(tags=["web-chat"])


class ChatRequest(BaseModel):
    """The body of a chat turn."""

    message: str = Field(min_length=1, max_length=8_000)


def get_chat_service(request: Request) -> ChatService:
    """The process-wide :class:`ChatService`, wired up at startup."""
    service: ChatService = request.app.state.chat_service
    return service


def _new_session_id() -> str:
    return secrets.token_urlsafe(16)


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,
    )


ServiceDep = Annotated[ChatService, Depends(get_chat_service)]
SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]


@router.get("/", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    service: ServiceDep,
    session: SessionCookie = None,
) -> Response:
    """Render the chat page, replaying any transcript this session already has."""
    session_id = session or _new_session_id()
    transcript = await service.history(session_id) if session else []
    draft = await service.draft_for(session_id) if session else None
    done = draft is not None and draft.status in {"filed", "scored", "escalated", "closed"}
    response = _TEMPLATES.TemplateResponse(
        request,
        "chat.html",
        {"transcript": transcript, "done": done},
    )
    if not session:
        _set_session_cookie(response, session_id)
    return response


@router.post("/chat")
async def chat_turn(
    payload: ChatRequest,
    service: ServiceDep,
    session: SessionCookie = None,
) -> JSONResponse:
    """Advance the conversation by one message and return the reply."""
    session_id = session or _new_session_id()
    try:
        turn = await service.handle(session_id, payload.message)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    response = JSONResponse({"reply": turn.reply, "done": turn.done, "status": turn.draft.status})
    if not session:
        _set_session_cookie(response, session_id)
    return response
