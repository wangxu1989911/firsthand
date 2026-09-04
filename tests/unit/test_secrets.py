"""secrets.py: authenticated encryption keyed only by the environment (§8.7)."""

from __future__ import annotations

import pytest

from firsthand import secrets
from firsthand.secrets import SecretKeyMissingError, decrypt, encrypt

_KEY = "a-master-key-from-the-environment"


def test_round_trips_with_an_explicit_key() -> None:
    token = encrypt("super-secret-token", key=_KEY)
    assert token != "super-secret-token"
    assert decrypt(token, key=_KEY) == "super-secret-token"


def test_ciphertext_is_non_deterministic() -> None:
    assert encrypt("x", key=_KEY) != encrypt("x", key=_KEY)


def test_a_wrong_key_cannot_decrypt() -> None:
    from cryptography.fernet import InvalidToken

    token = encrypt("payload", key=_KEY)
    with pytest.raises(InvalidToken):
        decrypt(token, key="a-different-key")


def test_the_key_falls_back_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRSTHAND_SECRET_KEY", _KEY)
    assert decrypt(encrypt("from-env")) == "from-env"


def test_a_missing_key_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRSTHAND_SECRET_KEY", raising=False)
    with pytest.raises(SecretKeyMissingError, match="FIRSTHAND_SECRET_KEY"):
        encrypt("anything")


def test_module_exports_the_stable_surface() -> None:
    assert set(secrets.__all__) == {"SecretKeyMissingError", "decrypt", "encrypt"}
