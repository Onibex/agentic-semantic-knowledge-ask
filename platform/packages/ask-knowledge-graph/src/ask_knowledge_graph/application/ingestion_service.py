"""
MetadataIngestionServiceWrapper — concrete impl of the IngestionService Protocol.

WRAP, not rewrite. The underlying `MetadataIngestionService` parses the YAML,
builds the right domain node (BronzeNode/SilverNode/GoldNode), and writes it.
This wrapper exposes the same flow through a typed Protocol so admin tooling
and the CLI depend on the Protocol only.

For backward compatibility, this module also re-exports that class itself as
`MetadataIngestionService`. New code should use
`MetadataIngestionServiceWrapper` + `IngestionRequest` directly.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.errors import IngestionError
from ..domain.models import EntityLayer, IngestionRequest, IngestionResult
from ..domain.ports import IngestionService, KnowledgeGraphWriter
from ..infrastructure.yaml_serializer import load_yaml_text

logger = logging.getLogger(__name__)


# `metric` is deliberately absent — the layer was removed, not deprecated.
# _detect_layer therefore returns None for it and the legacy service raises.
_VALID_LAYERS: set[str] = {"bronze", "silver", "gold"}


class MetadataIngestionServiceWrapper(IngestionService):
    """The default IngestionService — wraps the production legacy service.

    The legacy class is injected so this package does not bind to the legacy
    symbol directly (callers construct it once at startup).
    """

    def __init__(
        self,
        legacy_service: Any,
        writer: KnowledgeGraphWriter,
    ) -> None:
        self._legacy = legacy_service
        self._writer = (
            writer  # used for the typed delete path; legacy.execute_yaml_ingestion handles writes
        )

    def ingest_yaml(self, request: IngestionRequest) -> IngestionResult:
        if not request.yaml_content or not request.yaml_content.strip():
            return IngestionResult(error="Empty YAML content.")

        # Quick layer sniff so we can return a typed result before we even
        # invoke the legacy service. Mirrors the legacy detection logic.
        layer = _detect_layer(request.yaml_content, request.layer_override)
        entity_id = _detect_entity_id(request.yaml_content)

        try:
            raw_stats = self._legacy.execute_yaml_ingestion(request.yaml_content) or {}
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            logger.warning("ingest_yaml failed for entity_id=%s: %s", entity_id, exc)
            raise IngestionError(f"ingest_yaml failed: {exc}") from exc

        return IngestionResult(
            entity_id=entity_id,
            layer=layer,
            entities_indexed=int(raw_stats.get("entities", 0) or 0),
            fields_indexed=int(raw_stats.get("fields", 0) or 0),
            edges_indexed=int(raw_stats.get("edges", 0) or 0),
            error=None,
            raw_stats=raw_stats,
        )

    def ingest_sap_json(self, raw_json: dict[str, Any]) -> IngestionResult:
        if not isinstance(raw_json, dict) or not raw_json:
            return IngestionResult(error="Empty or invalid SAP JSON payload.")
        try:
            raw_stats = self._legacy.execute(raw_json) or {}
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            logger.warning("ingest_sap_json failed: %s", exc)
            raise IngestionError(f"ingest_sap_json failed: {exc}") from exc

        # Surface the Silver id at the top level (matches the shape produced
        # by ingest_yaml) so callers can do per-entity follow-ups (RAG
        # cascade in admin-api, downstream deletes, etc.) without reaching
        # into raw_stats. Bronze entities don't get an entity_id field —
        # they exist en bloc, not as a single addressable entity.
        silver_entity_id = raw_stats.get("silver_entity_id")
        return IngestionResult(
            entity_id=str(silver_entity_id) if silver_entity_id else None,
            entities_indexed=int(raw_stats.get("entities", 0) or 0),
            fields_indexed=int(raw_stats.get("fields", 0) or 0),
            edges_indexed=int(raw_stats.get("edges", 0) or 0),
            error=None,
            raw_stats=raw_stats,
        )

    def delete_entity(self, entity_id: str) -> IngestionResult:
        if not entity_id or not entity_id.strip():
            return IngestionResult(error="Empty entity_id.")
        stats = self._writer.delete_entity(entity_id.strip())
        return IngestionResult(
            entity_id=entity_id.strip(),
            entities_indexed=-int(stats.get("entities", 0) or 0),
            fields_indexed=-int(stats.get("fields", 0) or 0),
            edges_indexed=-int(stats.get("edges", 0) or 0),
            raw_stats=stats,
        )


# ─────────────────────────────────────────────────────────────────────────────
# YAML detection helpers (kept module-level so tests can hit them directly)
# ─────────────────────────────────────────────────────────────────────────────
def _detect_layer(yaml_content: str, override: EntityLayer | None) -> EntityLayer | None:
    if override:
        return override
    try:
        data = load_yaml_text(yaml_content)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    raw = (data.get("layer") or data.get("medallion_layer") or "").strip().lower()
    if raw in _VALID_LAYERS:
        return raw  # type: ignore[return-value]
    if raw:
        # Surface the unsupported layer to the caller via a typed exception.
        # The legacy ValueError gets translated by ingest_yaml's except branch
        # if we re-raise here, but we prefer to let detection be permissive
        # and let the legacy service raise — that path is well-tested.
        return None
    return None


def _detect_entity_id(yaml_content: str) -> str | None:
    try:
        data = load_yaml_text(yaml_content)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    eid = data.get("id")
    return str(eid) if eid else None


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compat re-export for admin tooling.
# The concrete class lives inside this package as `_legacy_ingestion`;
# the lazy lookup is kept in case any consumer still references it via the
# `from ask_knowledge_graph.application.ingestion_service import MetadataIngestionService`
# shape.
# ─────────────────────────────────────────────────────────────────────────────
def __getattr__(name: str) -> Any:
    if name == "MetadataIngestionService":
        from ._legacy_ingestion import MetadataIngestionService as _LegacyClass

        return _LegacyClass
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
