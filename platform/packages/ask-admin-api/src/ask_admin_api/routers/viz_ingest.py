# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""/v1/viz/merge/sap-json — SAP JSON merge from the visualizer SPA.

JWT-authenticated entry point for SAP JSON payloads driven by a human via
the SPA's "ASK Merge" panel (was previously "SAP Updates"). Internally
delegates to the canonical merge service (``sap_merge_service.merge_sap_payload``)
so this path and the M2M ``/v1/ingest/sap-json`` endpoint stay in lockstep —
same first-ingest behaviour, same conflict semantics, same git history shape.

Iter 1 rename (Req #4):
  * Canonical path: ``POST /v1/viz/merge/sap-json``
  * Deprecated alias: ``POST /v1/viz/ingest/sap-json`` — same handler, emits a
    deprecation log so consumers (Kafka Connect HTTP Sink, Watson X webhooks,
    legacy SPA bundles) keep working until they migrate. Remove the alias once
    no more deprecation logs show up in production for one full release cycle.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..application.git_service import GitService
from ..application.lifecycle_triggers import fire_on_merge
from ..application.sap_merge_service import MergeError, merge_sap_payload
from ..application.yaml_file_service import YAMLFileService
from ..auth.validator import TokenClaims, validate_token
from ..config import get_settings
from ..models.viz_models import (
    AutoAppliedChange,
    ConflictBlock,
    IngestSapJsonRequest,
    MergeResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/viz", tags=["viz"])

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


def _do_merge_sap_json(req: IngestSapJsonRequest, user: TokenClaims) -> MergeResult:
    """Shared handler for the canonical and the deprecated SAP-JSON paths."""
    settings = get_settings()
    repo_root = Path(settings.repo_root).resolve()
    baseline_root = repo_root / settings.baseline_path

    author_email = user.email
    author_name = author_email.split("@")[0]

    try:
        outcome = merge_sap_payload(
            req.payload,
            yaml_svc=_get_yaml_service(),
            git_svc=_get_git_service(),
            repo_root=repo_root,
            baseline_root=baseline_root,
            author_name=author_name,
            author_email=author_email,
            source_label="viz",
        )
    except MergeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # Lifecycle triggers: seed a doc for every first-ingest entity (Bronze +
    # Silver) so it shows in the catalog, and move a pre-existing merged Silver
    # back to "In Review". Shared with the M2M endpoint via fire_on_merge so
    # both SAP-JSON paths stay in lockstep (audit §5.3).
    fire_on_merge(
        created_entities=outcome.created_entities,
        silver_id=outcome.silver_id,
        working_changed=bool(outcome.auto_applied or outcome.baseline_updated),
    )

    return MergeResult(
        silver_id=outcome.silver_id,
        auto_applied=[AutoAppliedChange(**a) for a in outcome.auto_applied],
        conflicts=[ConflictBlock(**c) for c in outcome.conflicts],
        baseline_updated=outcome.baseline_updated,
        naming_warnings=outcome.naming_warnings,
    )


@router.post("/merge/sap-json", response_model=MergeResult)
async def merge_sap_json(
    req: IngestSapJsonRequest,
    user: TokenClaims = Depends(validate_token),
) -> MergeResult:
    """Merge an SAP JSON payload into workspace YAMLs (JWT, human-driven).

    Canonical endpoint for the new "ASK Merge" panel. Equivalent to the
    legacy ``/v1/viz/ingest/sap-json`` (kept as a deprecated alias).
    """
    return _do_merge_sap_json(req, user)


@router.post(
    "/ingest/sap-json",
    response_model=MergeResult,
    deprecated=True,
    summary="DEPRECATED — use /v1/viz/merge/sap-json instead",
)
async def ingest_sap_json_deprecated(
    req: IngestSapJsonRequest,
    user: TokenClaims = Depends(validate_token),
) -> MergeResult:
    """Deprecated alias of ``/v1/viz/merge/sap-json``.

    Emits a warning log on every call so we can see when the last legacy
    caller (old SPA bundle / Watson X integration) goes away. Same exact
    behaviour as the canonical path.
    """
    logger.warning(
        "deprecated path: POST /v1/viz/ingest/sap-json — migrate to /v1/viz/merge/sap-json",
        extra={"user_email": getattr(user, "email", "?")},
    )
    return _do_merge_sap_json(req, user)
