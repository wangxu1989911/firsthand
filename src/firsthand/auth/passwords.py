"""argon2id password hashing for admin accounts (design doc §8.7).

The plaintext is never stored: :func:`hash_password` produces an argon2id digest
and :func:`verify_password` checks a candidate against it in constant time.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

__all__ = ["hash_password", "verify_password"]

#: argon2-cffi's defaults are the OWASP-recommended argon2id parameters.
_hasher = PasswordHasher()


def hash_password(plaintext: str) -> str:
    """Return an argon2id hash for ``plaintext``."""
    if not plaintext:
        raise ValueError("password must not be empty")
    return _hasher.hash(plaintext)


def verify_password(password_hash: str, candidate: str) -> bool:
    """Return whether ``candidate`` matches ``password_hash``.

    A mismatch, a malformed stored hash, or an empty candidate all return
    ``False`` rather than raising — the caller only ever needs the boolean.
    """
    if not candidate:
        return False
    try:
        return _hasher.verify(password_hash, candidate)
    except VerificationError:
        return False
    except InvalidHashError:
        return False
