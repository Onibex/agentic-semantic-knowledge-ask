# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Runtime cache + os.environ exporter for the encrypted secrets backend.

Used by ``factory.build_llm`` / ``factory.build_embedder``:

  >>> provider = get_secrets_provider()
  >>> resolved = provider.get("llm")          # dict with provider/model/fields
  >>> provider.export_to_env("llm")           # seeds os.environ for LiteLLM

Cache TTL is short (60 s) so the orchestrator picks up SPA writes within ~1
minute. The admin-api invalidates the orchestrator's cache via the existing
``/v1/internal/reload`` endpoint when a write happens, so the TTL is just a
safety net.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from .repository import SecretsRepository

logger = logging.getLogger(__name__)


_CACHE_TTL_SECONDS = 60.0


class SecretsProvider:
    """Cached read-only view of ``ask-system-settings-v1`` for the runtime.

    Read API only: writes go through the admin-api router, which holds its own
    repository instance.
    """

    def __init__(
        self,
        repository: SecretsRepository | None = None,
        *,
        ttl_seconds: float = _CACHE_TTL_SECONDS,
    ) -> None:
        self._repo = repository or SecretsRepository()
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._lock = threading.Lock()

    # ── Reads ───────────────────────────────────────────────────────────────

    def get(self, target: str, *, force_refresh: bool = False) -> dict[str, Any] | None:
        """Return the resolved doc for ``target`` (decrypted fields included).

        Cached for ``ttl_seconds``. ``force_refresh=True`` bypasses the cache —
        called by the admin-api after writes so the next read is fresh.
        """
        now = time.monotonic()
        if not force_refresh:
            cached = self._cache.get(target)
            if cached is not None:
                stamp, value = cached
                if now - stamp < self._ttl:
                    return value

        try:
            resolved = self._repo.get_resolved(target)
        except PermissionError:
            # Stored cipher does not match current master key — surface upstream
            # as 503 instead of caching a bad result.
            logger.error("ENCRYPTION_KEY_MISMATCH while resolving %s", target)
            raise

        with self._lock:
            self._cache[target] = (now, resolved)
        return resolved

    def invalidate(self, target: str | None = None) -> None:
        """Drop cached entries. ``None`` drops everything; useful from /internal/reload."""
        with self._lock:
            if target is None:
                self._cache.clear()
            else:
                self._cache.pop(target, None)

    # ── Env-var export (for LiteLLM / boto3 / etc.) ─────────────────────────

    def export_to_env(self, target: str) -> list[str]:
        """Seed ``os.environ`` with every field of the resolved doc.

        Returns the list of env var names that were written, so callers can
        log or undo. Fields named ``api_key`` / ``api_base`` / ``api_version`` /
        ``deployment_id`` map to the LLM_/EMBEDDER_-prefixed env vars the
        ``factory.py`` resolution already understands; the rest (AWS_*,
        VERTEXAI_*, GOOGLE_APPLICATION_CREDENTIALS) are written verbatim.
        """
        resolved = self.get(target)
        if resolved is None:
            return []
        return _export_fields(target, resolved.get("fields") or {})


# ── Singleton accessor ──────────────────────────────────────────────────────


_singleton: SecretsProvider | None = None
_singleton_lock = threading.Lock()


def get_secrets_provider() -> SecretsProvider:
    """Process-wide singleton. Built lazily so tests can swap the repo first."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = SecretsProvider()
    return _singleton


def set_secrets_provider_for_tests(provider: SecretsProvider | None) -> None:
    """Test hook — override or reset the singleton."""
    global _singleton
    with _singleton_lock:
        _singleton = provider


# ── Helpers ─────────────────────────────────────────────────────────────────


# Convenience-field names that the existing factory.py resolves via the
# LLM_/EMBEDDER_ env var prefix. Anything not in this map gets written
# verbatim (AWS_*, VERTEXAI_*, GOOGLE_APPLICATION_CREDENTIALS).
_PREFIXED_FIELDS: dict[str, str] = {
    "api_key": "API_KEY",
    "api_base": "API_BASE",
    "api_version": "API_VERSION",
    "deployment_id": "DEPLOYMENT_ID",
}


def export_fields_to_env(plane: str, fields: dict[str, str]) -> list[str]:
    """Public: seed ``os.environ`` from an explicit ``fields`` map.

    ``plane`` is ``"llm"`` or ``"embedder"`` (selects the LLM_/EMBEDDER_ prefix
    for the convenience fields). Unlike :meth:`SecretsProvider.export_to_env`,
    this takes the resolved fields directly rather than reading a stored target —
    used by the LLM-connection ``/test`` probe, which has a specific (possibly
    non-active) connection's decrypted fields in hand.
    """
    return _export_fields(plane, fields)


def _export_fields(target: str, fields: dict[str, str]) -> list[str]:
    """Map field name → env var name + write to ``os.environ``.

    For ``target == "llm"`` a field named ``api_key`` becomes ``LLM_API_KEY``;
    for ``target == "embedder"`` it becomes ``EMBEDDER_API_KEY``. Provider-
    specific env vars (AWS_*, VERTEXAI_*) stay as-is.
    """
    prefix = "LLM_" if target == "llm" else "EMBEDDER_" if target == "embedder" else ""
    written: list[str] = []
    for name, value in fields.items():
        if value in (None, ""):
            continue
        if name in _PREFIXED_FIELDS and prefix:
            env_name = f"{prefix}{_PREFIXED_FIELDS[name]}"
        else:
            env_name = name
        if env_name:
            os.environ[env_name] = str(value)
            written.append(env_name)
    return written
