"""
SchemaResolverService — the SchemaService Protocol implementation.

Iter 5 strategy: WRAP the production-tested legacy SchemaCatalogService
rather than re-implement schema rendering. The legacy class stays in
`legacy/src/pipeline/application/schema_catalog_service.py` because the
v1 ask_graph still uses it internally as a fallback.

The wrapper exists so:
  - The orchestrator depends on the typed SchemaService Protocol, not on
    a class that lives under legacy/.
  - `import-linter` enforces that only this wrapper bridges to legacy
    (same pattern as Iter 4's OpenSearchKnowledgeGraphReader).
  - Iter 6+ can swap the legacy implementation for a refactor without
    touching consumers.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.models import SchemaQuery, SchemaResponse
from ..domain.ports import SchemaService

logger = logging.getLogger(__name__)


class SchemaResolverService(SchemaService):
    """SchemaService implementation backed by the legacy SchemaCatalogService."""

    def __init__(self, legacy_schema_catalog: Any) -> None:
        # Injected from outside — the orchestrator constructs the legacy
        # SchemaCatalogService(embedder, os_repository, llm) once at startup
        # and hands the instance over.
        self._legacy = legacy_schema_catalog

    def answer(self, query: SchemaQuery) -> SchemaResponse:
        if not query.question or not query.question.strip():
            return SchemaResponse(answer="", error="Empty schema question.")
        try:
            text = self._legacy.resolve_schema(
                query.question.strip(), allowed_ids=query.allowed_entity_ids
            )
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning("schema resolver failed: %s", exc)
            return SchemaResponse(
                answer=f"Pipeline error: {exc}",
                error=str(exc),
            )
        return SchemaResponse(answer=text or "")
