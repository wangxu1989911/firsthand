"""The admin area end to end through the ASGI app: auth, dashboard, config."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from asgi_lifespan import LifespanManager
from tests.fakes import FakeRedis
from tests.phase2support import (
    client,
    login,
    make_app,
    make_resources,
    make_settings,
    seed_admin,
)

from firsthand.admin.dashboard import DraftIndex
from firsthand.contracts import Conversation, DraftStatus, Evidence, IssueDraft
from firsthand.storage import RedisStateStore

PASSWORD = "correct-horse-battery-staple"


def _draft(session_id: str, *, status: DraftStatus = "gathering_info") -> IssueDraft:
    draft = IssueDraft(
        conversation=Conversation(surface="web", session_id=session_id),
        raw_text="the export is broken",
        redacted_text="the export is broken",
        category="bug",
    )
    draft.status = status
    draft.evidence.append(
        Evidence(source="jira", ref="PAY-1", snippet="known issue", retrieved_by="search_jira")
    )
    return draft


async def _store_draft(redis: FakeRedis, session_id: str, *, status: DraftStatus) -> None:
    state = RedisStateStore(cast(Any, redis), default_ttl_seconds=60)
    await state.set(session_id, _draft(session_id, status=status))
    await DraftIndex(cast(Any, redis)).register(session_id)


async def _logged_in_app(
    *, must_change_password: bool = False, settings: Any = None
) -> tuple[Any, FakeRedis]:
    redis = FakeRedis()
    await seed_admin(redis, must_change_password=must_change_password)
    app, _ = make_app(redis, settings=settings or make_settings())
    return app, redis


# ---------------------------------------------------------------------- auth


async def test_admin_root_redirects_to_the_dashboard() -> None:
    app, _ = await _logged_in_app()
    async with LifespanManager(app), client(app) as http:
        response = await http.get("/admin/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/dashboard"


async def test_admin_pages_bounce_anonymous_visitors_to_login() -> None:
    app, _ = await _logged_in_app()
    async with LifespanManager(app), client(app) as http:
        for path in ("/admin/dashboard", "/admin/config"):
            response = await http.get(path, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/admin/login"


async def test_login_page_renders() -> None:
    app, _ = await _logged_in_app()
    async with LifespanManager(app), client(app) as http:
        response = await http.get("/admin/login")
    assert response.status_code == 200
    assert "Sign in" in response.text


async def test_login_rejects_bad_credentials() -> None:
    app, _ = await _logged_in_app()
    async with LifespanManager(app), client(app) as http:
        wrong_pw = await http.post("/admin/login", data={"username": "admin", "password": "nope"})
        unknown = await http.post("/admin/login", data={"username": "ghost", "password": PASSWORD})
    assert wrong_pw.status_code == 401
    assert "Wrong username or password" in wrong_pw.text
    assert unknown.status_code == 401


async def test_login_reaches_the_dashboard_and_shows_the_session_user() -> None:
    app, _ = await _logged_in_app()
    async with LifespanManager(app), client(app) as http:
        signed_in = await login(http, password=PASSWORD)
        assert signed_in.status_code == 303
        assert signed_in.headers["location"] == "/admin/dashboard"

        dashboard = await http.get("/admin/dashboard")
    assert dashboard.status_code == 200
    assert "Dashboard" in dashboard.text


async def test_an_already_signed_in_user_is_redirected_off_the_login_page() -> None:
    app, _ = await _logged_in_app()
    async with LifespanManager(app), client(app) as http:
        await login(http, password=PASSWORD)
        response = await http.get("/admin/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/dashboard"


async def test_logout_ends_the_session() -> None:
    app, _ = await _logged_in_app()
    async with LifespanManager(app), client(app) as http:
        await login(http, password=PASSWORD)
        out = await http.post("/admin/logout", follow_redirects=False)
        assert out.status_code == 303
        assert out.headers["location"] == "/admin/login"

        after = await http.get("/admin/dashboard", follow_redirects=False)
    assert after.status_code == 303
    assert after.headers["location"] == "/admin/login"


# -------------------------------------------------------- forced password change


async def test_bootstrap_password_forces_a_change_before_anything_else() -> None:
    app, _ = await _logged_in_app(must_change_password=True)
    async with LifespanManager(app), client(app) as http:
        signed_in = await login(http, password=PASSWORD)
        assert signed_in.headers["location"] == "/admin/password"

        # The dashboard is off-limits until the password is rotated.
        blocked = await http.get("/admin/dashboard", follow_redirects=False)
        assert blocked.status_code == 303
        assert blocked.headers["location"] == "/admin/password"

        form = await http.get("/admin/password")
        assert "Change password" in form.text

        changed = await http.post(
            "/admin/password",
            data={
                "current_password": PASSWORD,
                "new_password": "a-much-longer-secret",
                "confirm_password": "a-much-longer-secret",
            },
            follow_redirects=False,
        )
        assert changed.status_code == 303
        assert changed.headers["location"] == "/admin/dashboard"

        now_ok = await http.get("/admin/dashboard")
    assert now_ok.status_code == 200


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "current_password": "wrong",
                "new_password": "a-much-longer-secret",
                "confirm_password": "a-much-longer-secret",
            },
            "Current password is wrong",
        ),
        (
            {
                "current_password": PASSWORD,
                "new_password": "a-much-longer-secret",
                "confirm_password": "different-secret-value",
            },
            "do not match",
        ),
        (
            {
                "current_password": PASSWORD,
                "new_password": "short",
                "confirm_password": "short",
            },
            "at least 12 characters",
        ),
    ],
)
async def test_password_change_validation(payload: dict[str, str], message: str) -> None:
    app, _ = await _logged_in_app(must_change_password=True)
    async with LifespanManager(app), client(app) as http:
        await login(http, password=PASSWORD)
        response = await http.post("/admin/password", data=payload)
    assert response.status_code == 400
    assert message in response.text


# ------------------------------------------------------------------ dashboard


async def test_dashboard_lists_stored_drafts_with_a_review_control() -> None:
    app, redis = await _logged_in_app()
    await _store_draft(redis, "s-open", status="gathering_info")
    await _store_draft(redis, "s-hot", status="escalated")
    async with LifespanManager(app), client(app) as http:
        await login(http, password=PASSWORD)
        page = await http.get("/admin/dashboard")
    assert page.status_code == 200
    assert "s-open" in page.text
    assert "s-hot" in page.text
    assert 'value="approve"' in page.text  # only the escalated row is reviewable


async def test_dashboard_surfaces_an_eval_report_when_configured(tmp_path: Path) -> None:
    report = tmp_path / "eval.json"
    report.write_text('{"precision": 0.9}', encoding="utf-8")
    app, _ = await _logged_in_app(settings=make_settings(eval_report_path=str(report)))
    async with LifespanManager(app), client(app) as http:
        await login(http, password=PASSWORD)
        page = await http.get("/admin/dashboard")
    assert "precision" in page.text


async def test_draft_detail_renders_state_and_evidence() -> None:
    app, redis = await _logged_in_app()
    await _store_draft(redis, "s-hot", status="escalated")
    await _store_draft(redis, "s-cold", status="scored")
    async with LifespanManager(app), client(app) as http:
        await login(http, password=PASSWORD)
        hot = await http.get("/admin/dashboard/drafts/s-hot")
        cold = await http.get("/admin/dashboard/drafts/s-cold")
        missing = await http.get("/admin/dashboard/drafts/nope")
    assert hot.status_code == 200
    assert "PAY-1" in hot.text
    assert "Approve &amp; file" in hot.text
    assert "Approve &amp; file" not in cold.text
    assert missing.status_code == 404


async def test_escalation_review_approves_rejects_and_validates() -> None:
    app, redis = await _logged_in_app()
    await _store_draft(redis, "s-1", status="escalated")
    await _store_draft(redis, "s-2", status="escalated")
    await _store_draft(redis, "s-open", status="gathering_info")
    async with LifespanManager(app), client(app) as http:
        await login(http, password=PASSWORD)

        approved = await http.post(
            "/admin/dashboard/drafts/s-1/review",
            data={"decision": "approve"},
            follow_redirects=False,
        )
        assert approved.status_code == 303
        detail = await http.get("/admin/dashboard/drafts/s-1")
        assert "filed" in detail.text

        rejected = await http.post(
            "/admin/dashboard/drafts/s-2/review",
            data={"decision": "reject"},
            follow_redirects=False,
        )
        assert rejected.status_code == 303
        assert "closed" in (await http.get("/admin/dashboard/drafts/s-2")).text

        bad_decision = await http.post(
            "/admin/dashboard/drafts/s-1/review", data={"decision": "sideways"}
        )
        assert bad_decision.status_code == 422

        gone = await http.post(
            "/admin/dashboard/drafts/absent/review", data={"decision": "approve"}
        )
        assert gone.status_code == 404

        not_ready = await http.post(
            "/admin/dashboard/drafts/s-open/review", data={"decision": "approve"}
        )
    assert not_ready.status_code == 409


# --------------------------------------------------------------------- config


async def test_connector_config_crud() -> None:
    app, _ = await _logged_in_app()
    async with LifespanManager(app), client(app) as http:
        await login(http, password=PASSWORD)

        empty = await http.get("/admin/config")
        assert "No connectors configured yet" in empty.text

        created = await http.post(
            "/admin/config",
            data={
                "connector_type": "jira",
                "base_url": "https://acme.atlassian.net",
                "credential": "api-token-value",
                "enabled": "true",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303

        listed = await http.get("/admin/config")
        assert "acme.atlassian.net" in listed.text
        assert ">set<" in listed.text
        assert "api-token-value" not in listed.text

        bad_type = await http.post(
            "/admin/config",
            data={"connector_type": "sharepoint", "base_url": "https://x", "credential": "c"},
        )
        assert bad_type.status_code == 422

        deleted = await http.post("/admin/config/jira/delete", follow_redirects=False)
        assert deleted.status_code == 303
        assert "No connectors configured yet" in (await http.get("/admin/config")).text

        bad_delete = await http.post("/admin/config/sharepoint/delete")
    assert bad_delete.status_code == 422


async def test_admin_area_is_unavailable_without_a_secret_key() -> None:
    redis = FakeRedis()
    await seed_admin(redis)
    app = _app_without_secret(redis)
    async with LifespanManager(app), client(app) as http:
        response = await http.get("/admin/login")
    assert response.status_code == 503


def _app_without_secret(redis: FakeRedis) -> Any:
    from firsthand.app import create_app

    settings = make_settings(secret_key="")
    return create_app(settings, resources=make_resources(redis))


async def test_a_deleted_account_mid_session_is_bounced_to_login() -> None:
    app, redis = await _logged_in_app()
    async with LifespanManager(app), client(app) as http:
        await login(http, password=PASSWORD)
        # The operator's user record disappears but the session cookie lingers:
        # require_rotated_password must not trust the stale session.
        for key in [k for k in redis.store if k.startswith("firsthand:admin:user")]:
            redis.store.pop(key)
        response = await http.get("/admin/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
