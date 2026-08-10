"""Store-backed DB-config resolution (2026-07 migration).

The DB-config plane used to live in ``config/settings.json`` under
``environments.{dev,prod}`` and was resolved by the pure function
``ask_sql_executor.application.db_target.resolve_db_target(settings, env)``.

It now lives in the encrypted OpenSearch store ``ask-system-settings-v1`` as
two singleton docs, ``db_dev`` and ``db_prod``. This module is the runtime
read path — it reads those docs through the cached :class:`SecretsProvider`
(so Fernet decryption happens once per TTL) and coerces the string-stored
fields back to native types (``port`` → int, ``secure`` / ``final`` → bool)
using the DB registry.

Resolution rules mirror the old resolver's per-env contract:

  * ``env`` ``None`` / ``"dev"`` / anything-but-``"prod"`` → ``db_dev`` doc.
  * ``env == "prod"``                                     → ``db_prod`` doc.
  * A missing / empty doc → an EMPTY ``db_config`` (the caller — the
    orchestrator — treats this as "not configured" and blocks the query with a
    clear message rather than silently querying the wrong database).

This module lives in ask-llm-gateway (the owner of the secrets store); the
orchestrator + flash strategy consume it. ask-sql-executor stays free of any
store dependency — it still just receives a ``(db_type, db_config)`` pair.
"""

from __future__ import annotations

import logging
from typing import Any

from .provider import SecretsProvider, get_secrets_provider
from .registry import db_provider_fields
from .repository import ACTIVE_POINTER_ID

logger = logging.getLogger(__name__)

# Default when nothing is configured — only ever paired with an empty config,
# so the concrete value is immaterial (the caller guards on emptiness first).
_DEFAULT_DB_TYPE = "postgresql"


def _target_for_env(env: str | None) -> str:
    """``prod`` → ``db_prod``; everything else (incl. ``None`` / ``dev``) → ``db_dev``.

    ``prod`` must be configured explicitly — it never inherits ``dev``.
    """
    return "db_prod" if env == "prod" else "db_dev"


def _coerce(db_type: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Coerce string-stored fields back to native types per the DB registry.

    Blank values are dropped (adapters treat a missing key as "use the driver
    default"). Unknown fields (not declared for this db_type) pass through as-is.
    """
    kinds = {name: kind for name, _sensitive, kind in db_provider_fields(db_type)}
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if value in (None, ""):
            continue
        kind = kinds.get(key, "str")
        if kind == "int":
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                out[key] = value
        elif kind == "bool":
            out[key] = str(value).strip().lower() in ("1", "true", "yes", "on")
        else:
            out[key] = value
    return out


def _env_key(env: str | None) -> str:
    """``prod`` → ``"prod"``; everything else (incl. ``None`` / ``dev``) → ``"dev"``."""
    return "prod" if env == "prod" else "dev"


def _resolved_to_pair(resolved: dict[str, Any] | None) -> tuple[str, dict[str, Any]] | None:
    """Turn a resolved store doc into ``(db_type, coerced_config)`` or None."""
    if not resolved or not resolved.get("provider"):
        return None
    db_type = str(resolved["provider"])
    return db_type, _coerce(db_type, dict(resolved.get("fields") or {}))


def resolve_db_config(
    env: str | None = None, *, provider: SecretsProvider | None = None
) -> tuple[str, dict[str, Any]]:
    """Return ``(db_type, db_config)`` for ``env`` from the encrypted store.

    Resolution order (2026-07 multi-DB):

      1. The active-connection pointer (``db_active``) → the connection doc
         registered as active for this env → its ``(db_type, config)``.
      2. Fallback: the legacy singleton doc (``db_dev`` / ``db_prod``). Keeps
         pre-migration deployments working during the window before the admin
         opens the new Database page (which imports the legacy docs into the
         registry).

    ``db_config`` is EMPTY when nothing is configured for the env — guard with
    :func:`is_db_configured`. ``provider`` is injectable for tests; it defaults
    to the process-wide singleton.
    """
    sp = provider or get_secrets_provider()

    # 1. Connection registry via the active pointer.
    try:
        pointer = sp.get(ACTIVE_POINTER_ID)
    except PermissionError:
        pointer = None  # pointer is never encrypted; be defensive anyway
    conn_id = None
    if pointer and pointer.get("fields"):
        conn_id = pointer["fields"].get(_env_key(env)) or None
    if conn_id:
        try:
            pair = _resolved_to_pair(sp.get(conn_id))
        except PermissionError:
            logger.error(
                "ENCRYPTION_KEY_MISMATCH resolving db connection %s (env=%s)", conn_id, env
            )
            return _DEFAULT_DB_TYPE, {}
        if pair is not None:
            return pair
        # Pointer references a missing/blank connection → fall through to legacy.

    # 2. Legacy singleton fallback.
    try:
        pair = _resolved_to_pair(sp.get(_target_for_env(env)))
    except PermissionError:
        # Master-key mismatch — surface as unconfigured rather than crashing the
        # request; the /internal/reload + boot key validation is the real guard.
        logger.error("ENCRYPTION_KEY_MISMATCH resolving db config for env=%s", env)
        return _DEFAULT_DB_TYPE, {}

    return pair if pair is not None else (_DEFAULT_DB_TYPE, {})


def is_db_configured(env: str | None = None, *, provider: SecretsProvider | None = None) -> bool:
    """True when ``env`` resolves to a non-empty DB connection in the store."""
    _db_type, db_config = resolve_db_config(env, provider=provider)
    return bool(db_config)


__all__ = ["is_db_configured", "resolve_db_config"]
