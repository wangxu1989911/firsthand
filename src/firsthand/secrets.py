"""Authenticated encryption for secrets at rest (design doc §8.7).

Connector credentials are encrypted before they are written to storage and
decrypted only in-process. The master key lives solely in the environment
(``FIRSTHAND_SECRET_KEY``); it is never persisted.

Phases 1, 3, and 4 import :func:`decrypt` to read connector credentials back, so
the two module-level signatures ``encrypt(plaintext: str) -> str`` and
``decrypt(ciphertext: str) -> str`` are a stable contract.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from firsthand.config import get_settings

__all__ = ["SecretKeyMissingError", "decrypt", "encrypt"]


class SecretKeyMissingError(RuntimeError):
    """Raised when a secret operation is attempted with no ``FIRSTHAND_SECRET_KEY``."""


def _fernet(key: str | None) -> Fernet:
    """Build a Fernet from the configured master key.

    The env value is an arbitrary string; it is stretched to Fernet's required
    32-byte url-safe base64 key with SHA-256 so operators are not forced to
    generate a key in one specific format.
    """
    material = get_settings().secret_key if key is None else key
    if not material:
        raise SecretKeyMissingError(
            "FIRSTHAND_SECRET_KEY is not set — it is required to encrypt or decrypt secrets"
        )
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str, *, key: str | None = None) -> str:
    """Return ciphertext for ``plaintext`` as a url-safe token string."""
    return _fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str, *, key: str | None = None) -> str:
    """Return the plaintext for a token produced by :func:`encrypt`.

    Propagates :class:`cryptography.fernet.InvalidToken` if the token was
    tampered with or was produced under a different key.
    """
    return _fernet(key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
