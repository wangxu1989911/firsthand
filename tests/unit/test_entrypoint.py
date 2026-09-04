"""`python -m firsthand` serves the app factory with the configured settings."""

from __future__ import annotations

from typing import Any

import pytest

import firsthand.__main__ as entrypoint


def test_main_serves_the_app_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeUvicorn:
        @staticmethod
        def run(target: str, **kwargs: Any) -> None:
            captured["target"] = target
            captured.update(kwargs)

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", FakeUvicorn)
    monkeypatch.setenv("FIRSTHAND_PORT", "9999")
    monkeypatch.setenv("FIRSTHAND_LOG_LEVEL", "DEBUG")

    entrypoint.main()

    assert captured["target"] == "firsthand.app:create_app"
    assert captured["factory"] is True
    assert captured["port"] == 9999
    assert captured["log_level"] == "debug"
