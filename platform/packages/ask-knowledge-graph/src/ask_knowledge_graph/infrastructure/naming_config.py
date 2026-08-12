"""Deployment-level resolution of the curated column naming mode.

Lives in ``infrastructure`` (not ``domain``): it reads the environment and the
optional ``config/settings.json``, which is I/O. The pure vocabulary
(:class:`ColumnNamingMode`) stays in ``domain.naming``.

Resolution order (first hit wins):

1. ``ASK_COLUMN_NAMING`` env var — the deployment switch (precedent:
   ``SEMANTIC_LAYER_AUTO_INIT``).
2. ``ingestion.column_naming`` in the caller-supplied config dict, or in
   ``config/settings.json`` (CWD-relative, same convention as
   ``admin_config._CONFIG_PATH``) when no dict is given.
3. :attr:`ColumnNamingMode.TECHNICAL` — the historical behavior.

An unrecognized value RAISES instead of silently defaulting: a misconfigured
mode would mint physical column names that do not match the client's tables,
which is the exact failure this flag exists to prevent. The mode is fixed
before the first ingest of a deployment and never changed on a populated
corpus (see REQ_CURATED_COLUMN_NAMING.md).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..domain.naming import ColumnNamingMode

logger = logging.getLogger(__name__)

_ENV_VAR = "ASK_COLUMN_NAMING"
_SETTINGS_PATH = Path("config/settings.json")


def _read_settings() -> dict[str, Any]:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse %s — ignoring it for column naming", _SETTINGS_PATH)
        return {}


def resolve_column_naming_mode(config: dict[str, Any] | None = None) -> ColumnNamingMode:
    """The deployment's :class:`ColumnNamingMode` (env > settings > technical)."""
    raw = (os.getenv(_ENV_VAR) or "").strip().lower()
    source = f"env {_ENV_VAR}"
    if not raw:
        settings = config if config is not None else _read_settings()
        ingestion = settings.get("ingestion") if isinstance(settings, dict) else None
        raw = str((ingestion or {}).get("column_naming") or "").strip().lower()
        source = "settings ingestion.column_naming"
    if not raw:
        return ColumnNamingMode.TECHNICAL
    try:
        return ColumnNamingMode(raw)
    except ValueError:
        valid = ", ".join(m.value for m in ColumnNamingMode)
        raise ValueError(
            f"Invalid column naming mode {raw!r} (from {source}); expected one of: {valid}. "
            "Refusing to default silently — the mode decides the physical column names "
            "minted at ingest."
        ) from None
