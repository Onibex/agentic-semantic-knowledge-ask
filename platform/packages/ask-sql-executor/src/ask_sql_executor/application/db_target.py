# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Per-environment database target resolution (UX_CHANGES audit CH-2, Iter 2).

.. note::
   As of the 2026-07 DB-config migration the RUNTIME read path is
   ``ask_llm_gateway.infrastructure.secrets.resolve_db_config`` (encrypted
   OpenSearch store), NOT this function. This pure ``settings``-dict resolver is
   retained for unit tests and any caller that still holds a settings dict; it
   returns an empty ``db_config`` once the DB blocks are stripped from
   ``settings.json`` by the migration.

Each environment points at its own target database. The connection is selected
from ``settings.json`` like so:

    {
      "db_type": "hana",
      "hana": { ...legacy/dev mirror... },
      "environments": {
        "dev":  { "db_type": "hana", "hana": { ...dev connection... } },
        "prod": { "db_type": "hana", "hana": { ...prod connection... } }
      }
    }

Resolution rules:

  * ``env`` present AND ``environments[env]`` is a non-empty, usable block
    → use that block.
  * ``env`` is ``None`` (legacy callers) OR ``"dev"`` with no usable block
    → fall back to the top-level block (the admin UI mirrors ``dev`` into it,
    so legacy single-DB deployments keep working).
  * ANY OTHER env (e.g. ``"prod"``) with no usable block → return an EMPTY
    ``db_config``. The orchestrator treats this as "not configured" and blocks
    the query with a clear message rather than silently querying the wrong
    (dev/top-level) database. Use :func:`is_db_configured` to detect it.

This is a pure function (no I/O) so it is trivially unit-testable and shared by
the orchestrator's execution path.
"""

from __future__ import annotations

from typing import Any

# Environments that may fall back to the legacy top-level block when they have
# no explicit ``environments[env]`` entry. ``dev`` falls back (the top-level is
# mirrored from dev); every other named env must be configured explicitly so a
# missing prod config never silently resolves to the dev/top-level database.
_TOP_LEVEL_FALLBACK_ENVS: frozenset[str | None] = frozenset({None, "dev"})


def resolve_db_target(
    settings: dict[str, Any], env: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Return ``(db_type, db_config)`` for ``env``.

    ``db_type`` is ``"hana"`` | ``"postgresql"``; ``db_config`` is the matching
    connection dict (a shallow copy — callers may mutate freely). ``db_config``
    is EMPTY when a non-fallback env (e.g. ``prod``) has no configured block —
    callers should guard with :func:`is_db_configured`.
    """
    environments = settings.get("environments") or {}
    block = environments.get(env) if env else None

    # 1. An explicit, non-empty per-env block wins.
    if isinstance(block, dict) and block:
        db_type = block.get("db_type") or settings.get("db_type") or "postgresql"
        db_config = block.get(db_type) or {}
        if db_config:
            return db_type, dict(db_config)

    # 2. ``None`` (legacy) and ``dev`` fall back to the top-level block.
    if env in _TOP_LEVEL_FALLBACK_ENVS:
        db_type = settings.get("db_type") or "postgresql"
        return db_type, dict(settings.get(db_type) or {})

    # 3. A named env with no usable block → unconfigured (empty db_config).
    return (settings.get("db_type") or "postgresql"), {}


def is_db_configured(settings: dict[str, Any], env: str | None = None) -> bool:
    """True when ``env`` resolves to a non-empty DB connection.

    ``prod`` (and any non-``dev`` named env) is considered configured ONLY when
    it has its own ``environments[env]`` block — it does not inherit the
    top-level/dev connection. ``dev`` / ``None`` fall back to the top-level
    block, so they are configured whenever any DB block exists.
    """
    _db_type, db_config = resolve_db_target(settings, env)
    return bool(db_config)


__all__ = ["resolve_db_target", "is_db_configured"]
