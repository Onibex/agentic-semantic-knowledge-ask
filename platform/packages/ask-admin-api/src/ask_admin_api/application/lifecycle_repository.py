"""OpenSearch CRUD for the DataProduct lifecycle index.

Index ``ask-entity-lifecycle-v1`` — one doc per DataProduct (= one YAML
entity). Doc id IS the ``entity_id`` so reads are a single ``GET _doc/<id>``.

This index is a denormalized cache of lifecycle state (status, version,
dev/prod publish records). It's the read path for the Semantic Knowledge
catalog, the workspace-home status dots, and the entity DetailPanel — zero git
reads at page-load time (UX_CHANGES audit §5).
"""

from __future__ import annotations

import logging
from typing import Any

from opensearchpy.exceptions import NotFoundError

from ..models.data_products import DataProductLifecycle
from .workspace_repository import _build_client

logger = logging.getLogger(__name__)

INDEX_ENTITY_LIFECYCLE = "ask-entity-lifecycle-v1"


_LIFECYCLE_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "entity_id": {"type": "keyword"},
            "workspace_id": {"type": "keyword"},
            "business_domain_ids": {"type": "keyword"},
            "status": {"type": "keyword"},
            "version": {"type": "integer"},
            "main_sha": {"type": "keyword"},
            "dev_published": {
                "type": "object",
                "properties": {
                    "version": {"type": "integer"},
                    "sha": {"type": "keyword"},
                    "at": {"type": "keyword"},
                    "by": {"type": "keyword"},
                },
            },
            "prod_published": {
                "type": "object",
                "properties": {
                    "version": {"type": "integer"},
                    "sha": {"type": "keyword"},
                    "at": {"type": "keyword"},
                    "by": {"type": "keyword"},
                },
            },
            "updated_at": {"type": "keyword"},
        }
    }
}


class LifecycleRepository:
    """OpenSearch CRUD for ``ask-entity-lifecycle-v1``."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client or _build_client()
        self._index_ensured = False

    # ── Index lifecycle ──────────────────────────────────────────────────────

    def ensure_index(self) -> None:
        """Create the lifecycle index if it doesn't exist. Idempotent."""
        if self._index_ensured:
            return
        try:
            if not self._client.indices.exists(index=INDEX_ENTITY_LIFECYCLE):
                self._client.indices.create(index=INDEX_ENTITY_LIFECYCLE, body=_LIFECYCLE_MAPPING)
                logger.info("Created OpenSearch index %s", INDEX_ENTITY_LIFECYCLE)
        except Exception:
            logger.exception("Failed to ensure index %s", INDEX_ENTITY_LIFECYCLE)
            raise
        self._index_ensured = True

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get(self, entity_id: str) -> DataProductLifecycle | None:
        self.ensure_index()
        try:
            doc = self._client.get(index=INDEX_ENTITY_LIFECYCLE, id=entity_id)
            return DataProductLifecycle(**doc["_source"])
        except NotFoundError:
            return None

    def list_all(self) -> list[DataProductLifecycle]:
        self.ensure_index()
        resp = self._client.search(
            index=INDEX_ENTITY_LIFECYCLE,
            body={"query": {"match_all": {}}, "size": 1000},
        )
        return [DataProductLifecycle(**h["_source"]) for h in resp["hits"]["hits"]]

    def list_by_workspace(self, workspace_id: str) -> list[DataProductLifecycle]:
        self.ensure_index()
        resp = self._client.search(
            index=INDEX_ENTITY_LIFECYCLE,
            body={"query": {"term": {"workspace_id": workspace_id}}, "size": 1000},
        )
        return [DataProductLifecycle(**h["_source"]) for h in resp["hits"]["hits"]]

    # ── Writes ──────────────────────────────────────────────────────────────────

    def upsert(self, doc: DataProductLifecycle) -> DataProductLifecycle:
        self.ensure_index()
        self._client.index(
            index=INDEX_ENTITY_LIFECYCLE,
            id=doc.entity_id,
            body=doc.model_dump(),
            refresh="wait_for",
        )
        return doc

    def delete(self, entity_id: str) -> bool:
        self.ensure_index()
        try:
            self._client.delete(index=INDEX_ENTITY_LIFECYCLE, id=entity_id, refresh="wait_for")
            return True
        except NotFoundError:
            return False
