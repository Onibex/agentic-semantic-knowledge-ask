# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
``/v1/ingest/*`` — machine-to-machine ingestion endpoints.

DIFFERENT PREFIX, DIFFERENT AUDIENCE
─────────────────────────────────────
The ``/admin/`` prefix is for the human-admin UI (XSUAA). The ``/ingest/``
prefix is for automated producers (Kafka Connect HTTP Sink, Watson X
webhooks, scheduled scripts). The two auth strategies are deliberately
disjoint:

  ``/v1/viz/ingest/sap-json``   →  XSUAA JWT (interactive human via SPA)
  ``/v1/ingest/sap-json``       →  X-API-Key (Kafka Connect / webhook)

Pass B (2026-05): both paths share the same merge service
(``sap_merge_service.merge_sap_payload``). No producer can publish to
runtime by accident — every SAP push lands as ``state: draft``,
auto-applies safe field changes against the workspace baseline, and
flags enriched-field changes as conflicts that a human must resolve.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException

from ..application.git_service import GitService
from ..application.lifecycle_triggers import fire_on_merge
from ..application.sap_merge_service import MergeError, merge_sap_payload
from ..application.yaml_file_service import YAMLFileService
from ..auth.api_key import verify_api_key
from ..config import get_settings
from ..models.viz_models import AutoAppliedChange, ConflictBlock, MergeResult
from ..models.yaml_ingestion import SapJsonIngestRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])

# ── Idempotency cache (in-memory, best-effort) ───────────────────────────────
# Producers can send ``Idempotency-Key`` to deduplicate retried SAP pushes.
# The cache is process-local — on restart, dedupe resets. For multi-replica
# deployments behind a load balancer we will need a shared store (Redis or an
# OpenSearch side index); flagged in PROJECT_VALIDATION_PENDING.
_IDEMPOTENCY_TTL_SECONDS = 3600  # 1h window
_idempotency_lock = threading.Lock()
_idempotency_cache: dict[str, tuple[float, dict]] = {}


def _idempotency_lookup(key: str) -> dict | None:
    if not key:
        return None
    now = time.time()
    with _idempotency_lock:
        # Trim expired entries opportunistically.
        expired = [
            k for k, (ts, _) in _idempotency_cache.items() if now - ts > _IDEMPOTENCY_TTL_SECONDS
        ]
        for k in expired:
            _idempotency_cache.pop(k, None)
        entry = _idempotency_cache.get(key)
        if not entry:
            return None
        ts, payload = entry
        if now - ts > _IDEMPOTENCY_TTL_SECONDS:
            _idempotency_cache.pop(key, None)
            return None
        return payload


def _idempotency_store(key: str, payload: dict) -> None:
    if not key:
        return
    with _idempotency_lock:
        _idempotency_cache[key] = (time.time(), payload)


# ── Lazy service singletons (shared with viz_ingest's intent, not its module
#    state — each router owns its own caches so resets are independent). ─────
_yaml_svc_lock = threading.Lock()
_yaml_svc: YAMLFileService | None = None
_git_svc_lock = threading.Lock()
_git_svc: GitService | None = None


def _get_yaml_service() -> YAMLFileService:
    global _yaml_svc
    if _yaml_svc is not None:
        return _yaml_svc
    with _yaml_svc_lock:
        if _yaml_svc is not None:
            return _yaml_svc
        s = get_settings()
        _yaml_svc = YAMLFileService(workspace_path=s.workspace_path, repo_root=s.repo_root)
    return _yaml_svc


def _get_git_service() -> GitService:
    global _git_svc
    if _git_svc is not None:
        return _git_svc
    with _git_svc_lock:
        if _git_svc is not None:
            return _git_svc
        s = get_settings()
        _git_svc = GitService(repo_root=s.repo_root)
    return _git_svc


@router.post("/sap-json", response_model=MergeResult)
async def ingest_sap_json_kafka(
    req: SapJsonIngestRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: dict = Depends(verify_api_key),
) -> MergeResult:
    """Merge an SAP JSON payload from an automated producer.

    Identical semantics to ``/v1/viz/ingest/sap-json`` — same first-ingest
    behaviour (creates missing entities as draft), same conflict logic,
    same git history shape. Only the auth dependency and the commit's
    ``source_label`` ("kafka") differ.

    ``Idempotency-Key`` is honoured best-effort against an in-process LRU
    cache (1h TTL). Repeated calls with the same key + same trace return
    the previously computed MergeResult.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "ingest sap-json received (machine)",
        extra={
            "trace_id": trace_id,
            "auth_method": principal.get("auth_method"),
            "principal": principal.get("principal"),
            "idempotency_key": idempotency_key,
        },
    )

    cached = _idempotency_lookup(idempotency_key or "")
    if cached is not None:
        logger.info("idempotency hit", extra={"trace_id": trace_id, "key": idempotency_key})
        return MergeResult(**cached)

    settings = get_settings()
    repo_root = Path(settings.repo_root).resolve()
    baseline_root = repo_root / settings.baseline_path

    # Machine producers don't have a human email — stamp commits with the
    # principal identity (the API-key label) and a fixed sap-ingestor mailbox.
    principal_name = str(principal.get("principal") or "sap-ingestor")
    author_email = "sap-ingestor@onibex.com"

    try:
        outcome = merge_sap_payload(
            req.data,
            yaml_svc=_get_yaml_service(),
            git_svc=_get_git_service(),
            repo_root=repo_root,
            baseline_root=baseline_root,
            author_name=principal_name,
            author_email=author_email,
            source_label="kafka",
        )
    except MergeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest sap-json failed", extra={"trace_id": trace_id})
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")

    # Lifecycle triggers — same as the SPA path so catalog visibility is
    # identical for human and machine ingests (audit §5.3).
    fire_on_merge(
        created_entities=outcome.created_entities,
        silver_id=outcome.silver_id,
        working_changed=bool(outcome.auto_applied or outcome.baseline_updated),
    )

    body = MergeResult(
        silver_id=outcome.silver_id,
        auto_applied=[AutoAppliedChange(**a) for a in outcome.auto_applied],
        conflicts=[ConflictBlock(**c) for c in outcome.conflicts],
        baseline_updated=outcome.baseline_updated,
        naming_warnings=outcome.naming_warnings,
    )

    if idempotency_key:
        _idempotency_store(idempotency_key, body.model_dump())

    return body
