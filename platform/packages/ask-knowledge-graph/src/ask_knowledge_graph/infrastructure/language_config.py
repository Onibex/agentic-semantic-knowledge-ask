"""Deployment-level resolution of the semantic layer's authoring language.

Lives in ``infrastructure`` (not ``domain``): it reads the environment and the
optional ``config/settings.json``, which is I/O. The pure vocabulary
(:class:`SemanticLanguage`) and the prompt directives stay in
``domain.language``. Mirrors ``naming_config`` deliberately — one flag shape for
both deployment-level authoring decisions.

Resolution order (first hit wins):

1. ``ASK_SEMANTIC_LANGUAGE`` env var — the deployment switch.
2. ``semantic_layer.language`` in the caller-supplied config dict, or in
   ``config/settings.json`` (CWD-relative) when no dict is given.
3. :attr:`SemanticLanguage.EN` — the historical behavior, so every existing
   deployment keeps working with no config change.

An unrecognized value RAISES instead of silently defaulting: authoring a corpus
in the wrong language is only discovered as *degraded retrieval*, never as an
error, and re-authoring means re-enriching + re-publishing everything. Same
reasoning as the column-naming resolver, and the same practical rule — decide it
before authoring the corpus.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..domain.language import SemanticLanguage

logger = logging.getLogger(__name__)

_ENV_VAR = "ASK_SEMANTIC_LANGUAGE"
_SETTINGS_PATH = Path("config/settings.json")


def _read_settings() -> dict[str, Any]:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse %s — ignoring it for semantic language", _SETTINGS_PATH)
        return {}
    return data if isinstance(data, dict) else {}


def resolve_semantic_language(config: dict[str, Any] | None = None) -> SemanticLanguage:
    """The deployment's :class:`SemanticLanguage` (env > settings > English)."""
    raw = (os.getenv(_ENV_VAR) or "").strip().lower()
    source = f"env {_ENV_VAR}"
    if not raw:
        settings = config if config is not None else _read_settings()
        section = settings.get("semantic_layer") if isinstance(settings, dict) else None
        raw = str((section or {}).get("language") or "").strip().lower()
        source = "settings semantic_layer.language"
    if not raw:
        return SemanticLanguage.EN
    try:
        return SemanticLanguage(raw)
    except ValueError:
        valid = ", ".join(m.value for m in SemanticLanguage)
        raise ValueError(
            f"Invalid semantic language {raw!r} (from {source}); expected one of: {valid}. "
            "Refusing to default silently — this decides the language the corpus is "
            "authored in AND the language retrieval queries are expressed in; a mismatch "
            "degrades retrieval without ever raising an error."
        ) from None
