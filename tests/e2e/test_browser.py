"""Browser coverage for Phase 2 (design doc §8.5).

These drive the real app in a headless browser. They are skipped automatically
when Playwright or its browser binaries are not installed, so they never break
the unit run; the route behaviour they check is also covered headlessly in
``tests/unit/test_web_routes.py`` and ``tests/unit/test_admin_routes.py`` for the
100% gate.

Run locally with::

    pip install playwright && playwright install chromium
    pytest -m e2e tests/e2e
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any, cast

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from playwright.sync_api import expect, sync_playwright
from tests.fakes import FakePool, FakeRedis
from tests.phase2support import make_settings

from firsthand.app import create_app
from firsthand.resources import AppResources

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return cast(int, sock.getsockname()[1])


@pytest.fixture
def live_server() -> Iterator[str]:
    redis = FakeRedis()
    resources = AppResources(
        cast(Any, FakePool()), cast(Any, redis), embedding_dimensions=3, state_ttl_seconds=3600
    )
    app = create_app(make_settings(), resources=resources)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        if not server.started:  # pragma: no cover - only on a stuck bind
            raise RuntimeError("uvicorn did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_chat_reply_renders_after_a_user_message(live_server: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{live_server}/")
        page.fill("#message", "the export button is broken")
        page.click("#chat-form button")
        expect(page.locator(".turn--assistant").first).to_be_visible()
        browser.close()


def test_admin_requires_login(live_server: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{live_server}/admin/dashboard")
        expect(page).to_have_url(f"{live_server}/admin/login")
        browser.close()
