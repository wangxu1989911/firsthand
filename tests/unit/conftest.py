"""Unit-test defaults for Phase 2.

``firsthand.secrets`` reads the master key from the process environment (as it
does in production). The Phase 2 tests inject a ``Settings`` object instead, so
this mirrors the same key into the environment for every unit test. Tests that
care about a missing key override this with their own ``monkeypatch``.
"""

from __future__ import annotations

import pytest

_TEST_SECRET_KEY = "test-secret-key-for-phase2"


@pytest.fixture(autouse=True)
def _phase2_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRSTHAND_SECRET_KEY", _TEST_SECRET_KEY)
