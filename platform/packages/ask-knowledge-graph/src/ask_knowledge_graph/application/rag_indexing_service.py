"""
ask_knowledge_graph.application.rag_indexing_service
─────────────────────────────────────────────────────────────────────────────
Application service for indexing chunked documents into the RAG collections
(`rag_schema`, `rag_data_product_docs`) and managing their lifecycle (list,
delete).

Replaces the inline logic that used to live in
``ask_admin_api.routers.embeddings`` — the router is now a thin transport
wrapper over this class. By centralising the embed + index + list + delete
flow here, both the unified YAML ingest endpoint (catalog + RAG in one
call) and the Documentation ingest endpoint share the same code path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import (
    Document,  # 0.3 + 1.x compatible (avoids langchain.schema eager import)
)

from ..infrastructure.rag_vectorstore_client import (
    _get_os_client,
    _index_for,
    get_or_create_opensearch_vectorstore,
)
from .rag_chunking import ChunkDoc

logger = logging.getLogger(__name__)


__all__ = [
    "IndexResult",
    "ListEntry",
    "ListResult",
    "DeleteResult",
    "RagIndexingService",
]


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class IndexResult:
    indexed: int = 0
    batches_sent: int = 0


@dataclass
class ListEntry:
    source_file: str
    table_name: str | None
    doc_count: int
    # entity_id is the canonical match key for joining a RAG entry to a
    # catalog entity (the renderer always stamps it on Silver/Gold chunks).
    # None when the chunk predates this field (legacy data) or comes from
    # rag_data_product_docs (documentation has no catalog correlate).
    entity_id: str | None = None


@dataclass
class ListResult:
    collection: str
    total_docs: int = 0
    entries: list[ListEntry] = field(default_factory=list)


@dataclass
class DeleteResult:
    deleted: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────
class RagIndexingService:
    """Embed + index + manage chunks in the RAG OpenSearch collections.

    The embedder + os_config are injected so callers can swap them in tests
    and the singleton lifecycle stays under the caller's control (admin-api
    keeps the singleton cached at the router level so reloads can drop it).
    """

    def __init__(self, embedder: Any, os_config: dict[str, Any], env: str | None = None) -> None:
        self._embedder = embedder
        self._os_config = os_config
        # Environment binding (Iter 2): suffixes the RAG index names so dev/prod
        # publishes stay isolated. None = legacy un-suffixed collection.
        self._env = env

    # ── Write ────────────────────────────────────────────────────────────────
    def index_chunks(
        self,
        collection: str,
        chunks: list[ChunkDoc],
        *,
        batch_size: int = 64,
    ) -> IndexResult:
        """Embed and index *chunks* into *collection*.

        The vectorstore handles embedding individually (SAP AI Core drops
        large batches), so *batch_size* only controls the OpenSearch bulk
        flushes — it doesn't change embedding behaviour.
        """
        if not chunks:
            return IndexResult(indexed=0, batches_sent=0)

        vectorstore = get_or_create_opensearch_vectorstore(
            self._os_config, collection, self._embedder, env=self._env
        )

        docs = [Document(page_content=c.page_content, metadata=dict(c.metadata)) for c in chunks]
        indexed = 0
        batches_sent = 0
        for i in range(0, len(docs), batch_size):
            batch = docs[i : i + batch_size]
            vectorstore.add_documents(batch)
            indexed += len(batch)
            batches_sent += 1
        return IndexResult(indexed=indexed, batches_sent=batches_sent)

    # ── Read ─────────────────────────────────────────────────────────────────
    def list_sources(self, collection: str) -> ListResult:
        """Aggregate indexed chunks by ``metadata.source_file``.

        Returns a count of unique source files + total chunks. Used by the
        Manage Embeddings UI to show what's indexed without dumping every
        chunk over the wire.
        """
        client = _get_os_client(self._os_config)
        index = _index_for(collection, self._env)

        if not client.indices.exists(index=index):
            return ListResult(collection=collection, total_docs=0, entries=[])

        total = client.count(index=index, body={"query": {"match_all": {}}})["count"]

        agg_body = {
            "size": 0,
            "aggs": {
                "by_source": {
                    "terms": {
                        "field": "metadata.source_file.keyword",
                        "size": 1000,
                        "missing": "__unknown__",
                    },
                    "aggs": {
                        "table_name": {
                            "terms": {
                                "field": "metadata.table_name.keyword",
                                "size": 1,
                            }
                        },
                        "entity_id": {
                            "terms": {
                                "field": "metadata.entity_id.keyword",
                                "size": 1,
                            }
                        },
                    },
                }
            },
        }
        resp = client.search(index=index, body=agg_body)
        entries: list[ListEntry] = []
        for bucket in resp.get("aggregations", {}).get("by_source", {}).get("buckets", []):
            tn_buckets = bucket.get("table_name", {}).get("buckets", [])
            eid_buckets = bucket.get("entity_id", {}).get("buckets", [])
            entries.append(
                ListEntry(
                    source_file=bucket["key"],
                    table_name=tn_buckets[0]["key"] if tn_buckets else None,
                    entity_id=eid_buckets[0]["key"] if eid_buckets else None,
                    doc_count=int(bucket["doc_count"]),
                )
            )
        return ListResult(collection=collection, total_docs=int(total), entries=entries)

    # ── Delete ───────────────────────────────────────────────────────────────
    def delete_documents(
        self,
        collection: str,
        source_files: list[str] | None = None,
        entity_ids: list[str] | None = None,
    ) -> DeleteResult:
        """Delete chunks. Precedence: *entity_ids* > *source_files* > wipe all.

        ``entity_ids`` is the canonical cascade path: when a catalog entity is
        deleted, the admin-api uses this to remove every RAG chunk produced
        by that entity (the renderer always stamps ``metadata.entity_id`` so
        the OpenSearch term filter is reliable). ``source_files`` stays for
        documentation deletion (rag_data_product_docs has no entity_id).
        """
        client = _get_os_client(self._os_config)
        index = _index_for(collection, self._env)

        if not client.indices.exists(index=index):
            return DeleteResult(deleted=0)

        if entity_ids:
            query = {"query": {"terms": {"metadata.entity_id.keyword": entity_ids}}}
        elif source_files:
            query = {"query": {"terms": {"metadata.source_file.keyword": source_files}}}
        else:
            query = {"query": {"match_all": {}}}

        resp = client.delete_by_query(index=index, body=query, refresh=True)
        return DeleteResult(deleted=int(resp.get("deleted", 0)))
