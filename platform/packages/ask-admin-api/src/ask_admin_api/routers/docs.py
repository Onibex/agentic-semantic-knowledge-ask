"""``POST /v1/admin/docs/ingest`` — multipart document upload, parse, chunk,
and index into the RAG embeddings store.

Supported formats
─────────────────
* ``.pdf``  — text extracted via ``pypdf``
* ``.docx`` — text extracted via ``python-docx``
* ``.txt``, ``.md``, ``.rst``, and all other extensions — decoded as UTF-8

Chunking
────────
``RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=80)`` from
LangChain, producing ``ChunkDoc`` instances from ``ask_knowledge_graph``.

Indexing
────────
Delegates to a lazy ``RagIndexingService`` singleton (same config-load pattern
as ``yaml_ingestion.py``). Collection defaults to ``rag_docs``.

Error handling
──────────────
All failures return ``DocIngestResult(error=...)`` — no HTTPException is raised
so the admin SPA can inspect the ``error`` field directly.
"""

from __future__ import annotations

import io
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/docs", tags=["admin/docs"])


# ── Lazy singleton ────────────────────────────────────────────────────────────

_rag_service_lock = threading.Lock()
_rag_service_singleton: Any = None


def reset_singletons() -> list[str]:
    """Drop the cached RagIndexingService so the next request rebuilds it from
    a fresh ``settings.json``."""
    global _rag_service_singleton
    cleared: list[str] = []
    if _rag_service_singleton is not None:
        cleared.append("docs_rag_service")
    _rag_service_singleton = None
    return cleared


def _load_config() -> dict[str, Any]:
    # Absent file degrades to {} — see application/runtime_config.py (BACKLOG 0).
    from ..application.runtime_config import load_runtime_config

    return load_runtime_config()


def _get_rag_service() -> Any:
    global _rag_service_singleton
    if _rag_service_singleton is not None:
        return _rag_service_singleton
    with _rag_service_lock:
        if _rag_service_singleton is not None:
            return _rag_service_singleton
        from ask_knowledge_graph.application.factory import (
            build_default_rag_indexing_service,
        )

        _rag_service_singleton = build_default_rag_indexing_service(_load_config())
        return _rag_service_singleton


# ── Response model ────────────────────────────────────────────────────────────


class DocIngestResult(BaseModel):
    chunks_indexed: int = 0
    batches_sent: int = 0
    collection: str = "rag_docs"
    error: str | None = None


# ── Text extraction helpers ───────────────────────────────────────────────────


def _extract_text(filename: str, content: bytes) -> str:
    """Extract plain text from *content* according to *filename*'s extension."""
    ext = Path(filename).suffix.lower() if filename else ""

    if ext == ".pdf":
        try:
            import pypdf  # type: ignore[import-untyped]

            reader = pypdf.PdfReader(io.BytesIO(content))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"PDF extraction failed: {exc}") from exc

    if ext == ".docx":
        try:
            import docx  # type: ignore[import-untyped]

            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"DOCX extraction failed: {exc}") from exc

    # Plain text (.txt, .md, .rst, or anything else)
    return content.decode("utf-8", errors="replace")


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post(
    "/ingest",
    response_model=DocIngestResult,
    summary="Upload and index a document into the RAG store",
)
async def ingest_document(
    file: UploadFile = File(...),
    collection_name: str = Form(default="rag_docs"),
    source_name: str = Form(default=""),
    user: TokenClaims = Depends(validate_token),
) -> DocIngestResult:
    trace_id = uuid.uuid4().hex
    filename = file.filename or ""
    logger.info(
        "POST /v1/admin/docs/ingest filename=%s collection=%s",
        filename,
        collection_name,
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    try:
        # 1. Read file bytes
        content = await file.read()

        # 2. Extract text
        text = _extract_text(filename, content)

        # 3. Guard — no text extracted
        if not text or not text.strip():
            return DocIngestResult(error="No text extracted from document")

        # 4. Chunk
        from langchain.text_splitter import (
            RecursiveCharacterTextSplitter,  # type: ignore[import-untyped]
        )

        splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=80)
        texts = splitter.split_text(text)

        if not texts:
            return DocIngestResult(error="No text chunks produced after splitting")

        # 5. Build ChunkDoc list
        from ask_knowledge_graph.application.rag_chunking import ChunkDoc

        _source = source_name or (filename or "uploaded_doc")
        chunks = [
            ChunkDoc(
                page_content=t,
                metadata={"source_file": _source, "chunk_index": i},
            )
            for i, t in enumerate(texts)
        ]

        logger.info(
            "[%s] chunks=%d source=%s",
            trace_id,
            len(chunks),
            _source,
            extra={"trace_id": trace_id, "auth_email": user.email},
        )

        # 6. Index
        result = _get_rag_service().index_chunks(collection_name, chunks)

        return DocIngestResult(
            chunks_indexed=result.indexed,
            batches_sent=result.batches_sent,
            collection=collection_name,
        )

    except Exception as exc:  # noqa: BLE001 — boundary: return error, don't raise
        logger.exception(
            "[%s] docs ingest failed",
            trace_id,
            extra={"trace_id": trace_id, "auth_email": user.email},
        )
        return DocIngestResult(error=str(exc))
