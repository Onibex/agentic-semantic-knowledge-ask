"""
Default-construction helper for the schema service (Iter 8.8).

Wires the legacy SchemaCatalogService (now in this package as
`_legacy_schema_catalog.py`) into the typed `SchemaResolverService`
wrapper. The orchestrator's `query.py` calls `build_default_schema_resolver()`
on first use; previously this wiring lived in `legacy_adapter.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema_resolver import SchemaResolverService


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
    cfg_path = Path("config/settings.json")
    if not cfg_path.exists():
        raise RuntimeError("config/settings.json not found — service must run from project root")
    return json.loads(cfg_path.read_text(encoding="utf-8"))
