"""``/v1/admin/embeddings/*`` — vectorstore indexing for the admin SPA Embeddings page.

Server-side responsibilities (admin):
  - Build the embeddings model from the configured AI Core deployment.
  - Open / create the OpenSearch vectorstore for the collection.
  - Embed and index the chunks the UI sends.

Client-side responsibilities (UI, local-only):
  - File parsing (PDF / DOCX / Excel / TXT).
  - Text cleaning + chunking (langchain text splitter).
  - Metadata enrichment + form fields.

The split keeps the SPA thin while letting heavy file parsing stay
client-local where it belongs (no need to ship multipart binary blobs).

Implementation note (Iter Knowledge refactor)
─────────────────────────────────────────────
The router is now a transport wrapper over
``ask_knowledge_graph.application.rag_indexing_service.RagIndexingService``.
Embedding + OpenSearch interaction live in the typed package; the router
only handles HTTP auth, DTO marshalling, and singleton caching.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth.validator import TokenClaims, validate_token
from ..models.embeddings import (
    DeleteDocumentsRequest,
    DeleteDocumentsResponse,
    DocumentChunk,
    EmbeddingEntry,
    IndexDocumentsRequest,
    IndexDocumentsResponse,
    ListDocumentsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/embeddings", tags=["admin/embeddings"])


# ── Lazy singletons ─────────────────────────────────────────────────────────
_service_lock = threading.Lock()
_service_singleton: Any = None


def reset_singletons() -> list[str]:
    """Drop the cached RagIndexingService so the next request rebuilds it
    from a fresh ``settings.json`` (singleton holds the embedder)."""
    global _service_singleton
    cleared: list[str] = []
    if _service_singleton is not None:
        cleared.append("rag_indexing_service")
    _service_singleton = None
    return cleared


def _load_config() -> dict[str, Any]:
    cfg_path = Path("config/settings.json")
    if not cfg_path.exists():
        raise RuntimeError("config/settings.json not found — service must run from project root")
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _get_service() -> Any:
    """Build the RagIndexingService once and reuse across requests."""
    global _service_singleton
    if _service_singleton is not None:
        return _service_singleton
    with _service_lock:
        if _service_singleton is not None:
            return _service_singleton
        from ask_knowledge_graph.application.factory import (
            build_default_rag_indexing_service,
        )

        _service_singleton = build_default_rag_indexing_service(_load_config())
        return _service_singleton


def _to_chunk_docs(chunks: list[DocumentChunk]) -> list[Any]:
    """Convert Pydantic chunks → KG ChunkDoc instances."""
    from ask_knowledge_graph.application.rag_chunking import ChunkDoc

    return [ChunkDoc(page_content=c.page_content, metadata=dict(c.metadata)) for c in chunks]


@router.post("/index", response_model=IndexDocumentsResponse)
async def index_documents(
    req: IndexDocumentsRequest,
    user: TokenClaims = Depends(validate_token),
) -> IndexDocumentsResponse:
    """Embed and index the supplied chunks into the named OpenSearch collection.

    Returns ``indexed`` (= count of chunks accepted) and ``batches_sent``
    so the UI can show progress / detect partial failures.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "embeddings index received",
        extra={
            "trace_id": trace_id,
            "collection": req.collection_name,
            "chunk_count": len(req.documents),
            "batch_size": req.batch_size,
            "auth_email": user.email,
            "auth_issuer": user.issuer,
        },
    )

    if not req.documents:
        return IndexDocumentsResponse(indexed=0, batches_sent=0)

    try:
        result = _get_service().index_chunks(
            req.collection_name,
            _to_chunk_docs(req.documents),
            batch_size=req.batch_size,
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("embeddings index failed", extra={"trace_id": trace_id})
        raise HTTPException(status_code=500, detail=f"Index failed: {exc}")

    return IndexDocumentsResponse(indexed=result.indexed, batches_sent=result.batches_sent)


@router.get("/{collection_name}/list", response_model=ListDocumentsResponse)
async def list_documents(
    collection_name: str,
    user: TokenClaims = Depends(validate_token),
) -> ListDocumentsResponse:
    """Return a summary of all source files indexed in a collection."""
    try:
        result = _get_service().list_sources(collection_name)
    except Exception as exc:
        logger.exception("embeddings list failed")
        raise HTTPException(status_code=500, detail=f"List failed: {exc}")

    return ListDocumentsResponse(
        collection=result.collection,
        total_docs=result.total_docs,
        entries=[
            EmbeddingEntry(
                source_file=e.source_file,
                table_name=e.table_name,
                entity_id=e.entity_id,
                doc_count=e.doc_count,
            )
            for e in result.entries
        ],
    )


@router.delete("/{collection_name}", response_model=DeleteDocumentsResponse)
async def delete_documents(
    collection_name: str,
    req: DeleteDocumentsRequest,
    user: TokenClaims = Depends(validate_token),
) -> DeleteDocumentsResponse:
    """Delete embeddings from a collection. ``entity_ids`` wins over
    ``source_files``; if neither is set, the entire collection is wiped."""
    try:
        result = _get_service().delete_documents(
            collection_name,
            source_files=req.source_files,
            entity_ids=req.entity_ids,
        )
        logger.info(
            "embeddings deleted",
            extra={
                "collection": collection_name,
                "source_files": req.source_files,
                "entity_ids": req.entity_ids,
                "deleted": result.deleted,
                "auth_email": user.email,
            },
        )
    except Exception as exc:
        logger.exception("embeddings delete failed")
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")

    return DeleteDocumentsResponse(deleted=result.deleted)
