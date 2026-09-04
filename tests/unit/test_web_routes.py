"""The public web-chat routes, driven through the ASGI app."""

from __future__ import annotations

from asgi_lifespan import LifespanManager
from tests.phase2support import client, make_app

from firsthand.web.routes import SESSION_COOKIE


async def test_chat_page_starts_a_session_for_a_fresh_visitor() -> None:
    app, _ = make_app()
    async with LifespanManager(app), client(app) as http:
        response = await http.get("/")
    assert response.status_code == 200
    assert "File a feature request" in response.text
    assert SESSION_COOKIE in response.cookies


async def test_a_chat_turn_returns_a_reply_and_persists_the_session() -> None:
    app, _ = make_app()
    async with LifespanManager(app), client(app) as http:
        first = await http.post("/chat", json={"message": "the export button is broken"})
        assert first.status_code == 200
        body = first.json()
        assert body["reply"]
        assert body["done"] is False
        assert SESSION_COOKIE in first.cookies

        # The follow-up rides the session cookie and moves the draft forward.
        second = await http.post("/chat", json={"message": "click export, nothing happens"})
        assert second.status_code == 200

        page = await http.get("/")
    assert "the export button is broken" in page.text


async def test_a_completed_conversation_locks_the_page() -> None:
    app, _ = make_app()
    async with LifespanManager(app), client(app) as http:
        for message in ["please add dark mode", "night work hurts", "a settings toggle"]:
            done = (await http.post("/chat", json={"message": message})).json()["done"]
        assert done is True
        page = await http.get("/")
    assert "complete" in page.text.lower()


async def test_a_whitespace_only_message_is_rejected() -> None:
    app, _ = make_app()
    async with LifespanManager(app), client(app) as http:
        response = await http.post("/chat", json={"message": " "})
    assert response.status_code == 422


async def test_the_page_replays_nothing_for_an_unseen_session() -> None:
    app, _ = make_app()
    async with LifespanManager(app), client(app) as http:
        http.cookies.set(SESSION_COOKIE, "never-used")
        response = await http.get("/")
    assert response.status_code == 200
    assert SESSION_COOKIE not in response.cookies
