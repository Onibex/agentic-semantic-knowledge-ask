"""``/v1/admin/catalog`` + ``/v1/admin/lifecycle/...`` — DataProduct lifecycle.

The catalog is the read path for the Semantic Knowledge page (UX_CHANGES audit
CH-0 / §5.5): a flat list of every DataProduct's lifecycle state (status,
version, dev/prod publish, business-domain membership). Display columns that
need entity metadata (layer, module, name, role) are joined client-side against
``GET /v1/viz/yamls`` — this endpoint stays a single fast OpenSearch read.

The rebuild endpoint (audit §5.6) is the reconciliation safety net.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from ..application.conflict_store import ConflictStore
from ..application.lifecycle_service import LifecycleService
from ..application.workspace_service import WorkspaceService
from ..auth.validator import TokenClaims, validate_token
from ..config import get_settings
from ..models.data_products import (
    CatalogRow,
    DataProductStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin/lifecycle"])

_lifecycle: LifecycleService | None = None
_workspaces: WorkspaceService | None = None


def _lifecycle_service() -> LifecycleService:
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = LifecycleService()
    return _lifecycle


def _workspace_service() -> WorkspaceService:
    global _workspaces
    if _workspaces is None:
        _workspaces = WorkspaceService()
    return _workspaces


def _conflict_store() -> ConflictStore:
    s = get_settings()
    return ConflictStore(Path(s.repo_root).resolve() / s.baseline_path)


def _pending_conflict_counts() -> dict[str, int]:
    """Per-entity unresolved-conflict counts, derived from the sidecars (O(files),
    same source as GET /v1/viz/conflicts/pending). A conflict is an orthogonal
    attribute layered on the lifecycle status, never stored in the index."""
    counts: dict[str, int] = {}
    for c in _conflict_store().list_all_pending():
        yid = c.get("yaml_id")
        if yid:
            counts[yid] = counts.get(yid, 0) + 1
    return counts


@router.get("/catalog", response_model=list[CatalogRow])
async def get_catalog(
    workspace_id: str | None = Query(default=None),
    status: DataProductStatus | None = Query(default=None),
    _claims: TokenClaims = Depends(validate_token),
) -> list[CatalogRow]:
    """All DataProduct lifecycle docs (+ derived pending_conflicts), optionally
    filtered by workspace / status."""
    svc = _lifecycle_service()
    docs = svc.list_by_workspace(workspace_id) if workspace_id else svc.list_all()
    if status is not None:
        docs = [d for d in docs if d.status == status]
    counts = _pending_conflict_counts()
    return [
        CatalogRow(**d.model_dump(), pending_conflicts=counts.get(d.entity_id, 0)) for d in docs
    ]


@router.get("/lifecycle/{entity_id}", response_model=CatalogRow | None)
async def get_lifecycle(
    entity_id: str,
    _claims: TokenClaims = Depends(validate_token),
) -> CatalogRow | None:
    """Lifecycle doc for one DataProduct (+ derived pending_conflicts) for the
    entity DetailPanel. ``null`` if absent."""
    doc = _lifecycle_service().get(entity_id)
    if doc is None:
        return None
    pending = len(_conflict_store().list_for(entity_id))
    return CatalogRow(**doc.model_dump(), pending_conflicts=pending)


@router.post("/lifecycle/rebuild", status_code=200)
async def rebuild_lifecycle(
    _claims: TokenClaims = Depends(validate_token),
) -> dict[str, int]:
    """Reseed the lifecycle index membership from current Business Domains.

    Reconciliation safety net (audit §5.6) — use after a PVC restore, manual
    git ops, or index corruption. Iter 1 reseeds membership only; full git-based
    status/version reconciliation lands with the git-flow in Iter 3.
    """
    all_bds = _workspace_service().list_all_business_domains()
    touched = _lifecycle_service().rebuild(all_bds)
    return {"data_products_touched": touched}
