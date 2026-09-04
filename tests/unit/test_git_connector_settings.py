"""FIRSTHAND_GIT_* settings parsing and the repo-slug guard."""

from __future__ import annotations

import os

import pytest

from firsthand.connectors.git.settings import (
    GitConnectorSettings,
    is_valid_repo,
    parse_repo_list,
)


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("FIRSTHAND_GIT_"):
            monkeypatch.delenv(key, raising=False)


def test_parse_repo_list_splits_on_commas_and_whitespace_and_dedupes() -> None:
    assert parse_repo_list("a/b, c/d  a/b\ne/f") == ["a/b", "c/d", "e/f"]


def test_parse_repo_list_is_empty_for_blank() -> None:
    assert parse_repo_list("   ") == []


@pytest.mark.parametrize(
    "repo,ok",
    [
        ("acme/store", True),
        ("acme/store.js", True),
        ("group/sub/project", True),
        ("no-slash", False),
        ("../etc/passwd", False),
        ("acme/store?x=1", False),
        ("acme/ store", False),
    ],
)
def test_is_valid_repo(repo: str, ok: bool) -> None:
    assert is_valid_repo(repo) is ok


def test_repo_list_property_reads_from_the_raw_field() -> None:
    settings = GitConnectorSettings(repos="acme/store x/y")
    assert settings.repo_list == ["acme/store", "x/y"]


def test_defaults_are_sane() -> None:
    settings = GitConnectorSettings()
    assert settings.host_kind == "github"
    assert settings.churn_window_days == 90
    assert settings.max_api_calls == 20
    assert settings.repo_list == []
