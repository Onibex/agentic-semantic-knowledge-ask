# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Default-construction helper for the schema service (Iter 8.8).

Wires the legacy SchemaCatalogService (now in this package as
`_legacy_schema_catalog.py`) into the typed `SchemaResolverService`
wrapper. The orchestrator's `query.py` calls `build_default_schema_resolver()`
on first use; previously this wiring lived in `legacy_adapter.py`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .schema_resolver import SchemaResolverService

logger = logging.getLogger(__name__)


def build_default_schema_resolver(env: str | None = None) -> SchemaResolverService:
    """Construct a `SchemaResolverService` ready to answer SCHEMA_QUERY intents.

    ``env`` (dev/prod/None) selects the env-suffixed registry indices so a
    SCHEMA_QUERY reads the same environment the chat user picked.
    """
    from ask_knowledge_graph.infrastructure.opensearch_repository import (
        OpenSearchAskRepository,
    )
    from ask_llm_gateway.application.factory import build_embedder, build_llm

    from ._legacy_schema_catalog import SchemaCatalogService

    cfg = _load_config()
    llm = build_llm(cfg)
    embedder = build_embedder(cfg)
    os_repo = OpenSearchAskRepository(env=env)
    legacy_svc: Any = SchemaCatalogService(embedder=embedder, os_repository=os_repo, llm=llm)
    return SchemaResolverService(legacy_schema_catalog=legacy_svc)


def _load_config() -> dict[str, Any]:
    """Read ``config/settings.json``; ``{}`` when absent or unreadable.

    Never raises: the file is gitignored (a fresh clone has none) and env vars
    carry every key that matters, so absence must degrade, not crash a request
    path (BACKLOG group 0, P1 — hit live 2026-08-12)."""
    cfg_path = Path("config/settings.json")
    if not cfg_path.exists():
        logger.warning(
            "config/settings.json not found (resolved=%s, cwd=%s) — using environment only",
            cfg_path.resolve(),
            os.getcwd(),
        )
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a broken file must not take the service down
        logger.warning("config/settings.json is not valid JSON — ignoring it")
        return {}
    return data if isinstance(data, dict) else {}
