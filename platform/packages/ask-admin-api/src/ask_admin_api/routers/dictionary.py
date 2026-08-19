# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/dictionary`` — semantic dictionary CRUD.

Backed by ``ask_knowledge_graph.application.factory.build_default_dictionary_writer``.
Only the two methods the admin SPA consumes are exposed:
``upsert_entry_global`` and ``list_entries_global``.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth.validator import TokenClaims, validate_token
from ..models.dictionary import (
    DictionaryDeleteResponse,
    DictionaryEntry,
    DictionaryListResponse,
    DictionaryUpsertResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin/dictionary"])


# ── Lazy singleton — built on first request, thread-safe ────────────────────
_writer_lock = threading.Lock()
_writer_singleton: Any = None


def reset_singletons() -> list[str]:
    """Drop the cached DictionaryWriter so the next request rebuilds it
    from a fresh ``settings.json``."""
    global _writer_singleton
    cleared: list[str] = []
    if _writer_singleton is not None:
        cleared.append("dictionary_writer")
    _writer_singleton = None
    return cleared


def _get_writer() -> Any:
    """Build the typed ``DictionaryWriter`` once and reuse across requests."""
    global _writer_singleton
    if _writer_singleton is not None:
        return _writer_singleton
    with _writer_lock:
        if _writer_singleton is not None:
            return _writer_singleton
        from ask_knowledge_graph.application.factory import (
            build_default_dictionary_writer,
        )

        from ..application.runtime_config import load_runtime_config

        cfg = load_runtime_config()
        _writer_singleton = build_default_dictionary_writer(cfg)
        return _writer_singleton


@router.post(
    "/dictionary",
    response_model=DictionaryUpsertResponse,
    responses={500: {"description": "Upsert failed"}},
)
async def upsert_dictionary_entry(
    entry: DictionaryEntry,
    user: TokenClaims = Depends(validate_token),
) -> DictionaryUpsertResponse:
    """Upsert one mapping (field / metric / phrase). Generates the embedding
    on the server side via ``DictionaryWriter.upsert_entry_global``."""
    trace_id = uuid.uuid4().hex
    logger.info(
        "dictionary upsert",
        extra={
            "trace_id": trace_id,
            "type": entry.type,
            "canonical_label": entry.canonical_label,
            # Key is not "module" because that conflicts with LogRecord.module.
            "dict_module": entry.module,
            "auth_email": user.email,
            "auth_issuer": user.issuer,
        },
    )
    try:
        ok = _get_writer().upsert_entry_global(entry.model_dump())
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("dictionary upsert failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=500,
            detail=f"Upsert failed: {exc}",
        )
    if not ok:
        return DictionaryUpsertResponse(
            success=False,
            message="DictionaryWriter returned False (check OpenSearch connectivity).",
        )
    return DictionaryUpsertResponse(success=True, message="Entry saved.")


@router.get("/dictionary", response_model=DictionaryListResponse)
async def list_dictionary_entries(
    module: str | None = Query(
        default=None, description="Filter by SAP module (SD, MM, PP, FI, CO)."
    ),
    type_filter: str = Query(
        default="phrase",
        description="Filter by entry type (phrase, metric, dimension, …). Defaults to 'phrase'.",
    ),
    user: TokenClaims = Depends(validate_token),
) -> DictionaryListResponse:
    """List dictionary entries, optionally filtered by ``module`` and ``type_filter``.

    By default only ``phrase`` entries are returned — the SPA only manages
    business-term phrases. Pass ``?type_filter=metric`` (or any other type)
    to access field/metric mappings when needed.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "dictionary list",
        extra={
            "trace_id": trace_id,
            # Key is not "module" because that conflicts with LogRecord.module.
            "dict_module": module,
            "type_filter": type_filter,
            "auth_email": user.email,
            "auth_issuer": user.issuer,
        },
    )
    try:
        entries = _get_writer().list_entries_global(module=module)
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("dictionary list failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=500,
            detail=f"List failed: {exc}",
        )
    filtered = []
    for e in entries or []:
        if e.get("type") == type_filter:
            entry = dict(e)
            if "_id" in entry:
                entry["id"] = entry.pop("_id")
            filtered.append(entry)
    return DictionaryListResponse(entries=filtered)


@router.delete(
    "/dictionary/{entry_id}",
    response_model=DictionaryDeleteResponse,
    responses={404: {"description": "Entry not found"}, 500: {"description": "Delete failed"}},
)
async def delete_dictionary_entry(
    entry_id: str,
    user: TokenClaims = Depends(validate_token),
) -> DictionaryDeleteResponse:
    """Delete a single dictionary entry by its OpenSearch document id.

    ``entry_id`` is the ``_id`` field returned by ``GET /v1/admin/dictionary``
    (e.g. ``"SD_s4h_net_value"``).  Only ``phrase`` entries are expected here
    from the SPA, but the endpoint is type-agnostic.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "dictionary delete",
        extra={
            "trace_id": trace_id,
            "entry_id": entry_id,
            "auth_email": user.email,
            "auth_issuer": user.issuer,
        },
    )
    try:
        ok = _get_writer().delete_entry_global(entry_id)
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("dictionary delete failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=500,
            detail=f"Delete failed: {exc}",
        )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Entry '{entry_id}' not found in the semantic dictionary.",
        )
    return DictionaryDeleteResponse(success=True, message=f"Entry '{entry_id}' deleted.")
