"""Fernet symmetric encryption for provider secrets.

The master key lives in the ``ONIBEX_ENCRYPTION_KEY`` env var (K8s Secret in
production). Fernet provides AES-128-CBC + HMAC-SHA256 authenticated encryption
in a single primitive — tampering is detected on ``decrypt``.

Failure modes are intentionally fatal at module-init time:
  * Key missing                       → ``ENCRYPTION_KEY_MISSING`` (SystemExit)
  * Key not 32-byte urlsafe-b64       → ``ENCRYPTION_KEY_INVALID_FORMAT``
  * Stored cipher does not match key  → ``PermissionError(ENCRYPTION_KEY_MISMATCH)``
                                        at decrypt time (handled by the router/runtime)

Generating a new key (developer terminal):

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTION_KEY_ENV = "ONIBEX_ENCRYPTION_KEY"


class EncryptionKeyMissingError(SystemExit):
    """Raised at boot when the master key is not configured."""


class EncryptionKeyInvalidError(SystemExit):
    """Raised at boot when the master key is malformed (not 32-byte urlsafe-b64)."""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Build a Fernet instance from the env var. Cached — single instance per process.

    Fail-closed: raises SystemExit so the process aborts at first use if the key
    is missing or malformed. We don't want any code path that silently runs
    without crypto.
    """
    raw = os.environ.get(ENCRYPTION_KEY_ENV, "").strip()
    if not raw:
        raise EncryptionKeyMissingError(
            f"ENCRYPTION_KEY_MISSING: set {ENCRYPTION_KEY_ENV} in the environment"
        )
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionKeyInvalidError(
            f"ENCRYPTION_KEY_INVALID_FORMAT: {ENCRYPTION_KEY_ENV} must be a 32-byte "
            f"urlsafe-base64 string (Fernet.generate_key() output). Underlying: {exc}"
        ) from exc


def encrypt(plaintext: str) -> str:
    """Return a Fernet token (urlsafe-base64 str) for ``plaintext``."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Reverse ``encrypt``. Raises ``PermissionError`` on bad token / key mismatch."""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise PermissionError("ENCRYPTION_KEY_MISMATCH") from exc


def validate_master_key() -> None:
    """Boot-time check. Call from FastAPI lifespan. No-op if the key is valid.

    Raises ``SystemExit`` (via the underlying helpers) on missing / malformed key,
    which FastAPI converts into a clean abort with the message in stderr.
    """
    _get_fernet()  # touches the cached instance; SystemExit if invalid


def reset_cache_for_tests() -> None:
    """Tests-only: drop the cached Fernet so a new env var takes effect."""
    _get_fernet.cache_clear()
