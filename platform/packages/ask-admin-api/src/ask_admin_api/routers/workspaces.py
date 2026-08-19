# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/workspaces/...`` — CRUD for Workspaces + nested Business Domains.

The workspace hierarchy (UX_CHANGES audit, Iter 1). "Data Product" was renamed
to "Business Domain" — see ``models/workspaces.py``.

Routes
──────
GET    /v1/admin/workspaces                                     list all
POST   /v1/admin/workspaces                                     create
GET    /v1/admin/workspaces/{id_or_slug}                        get by id or slug
PATCH  /v1/admin/workspaces/{id_or_slug}                        partial update
DELETE /v1/admin/workspaces/{id_or_slug}                        cascade delete
GET    /v1/admin/workspaces/{id_or_slug}/business-domains       list BDs in WS
POST   /v1/admin/workspaces/{id_or_slug}/business-domains       create BD in WS
GET    /v1/admin/workspaces/{id_or_slug}/entity-ids             flat DP-id list (chat scope)

Singleton BD endpoints (id-only) live in ``business_domains.py``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..application.workspace_service import (
    BusinessDomainNotFoundError,
    SlugConflictError,
    WorkspaceNotFoundError,
    WorkspaceService,
)
from ..auth.validator import TokenClaims, require_role, validate_token
from ..models.workspaces import (
    BusinessDomain,
    BusinessDomainCreate,
    Workspace,
    WorkspaceCreate,
    WorkspaceUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/workspaces", tags=["admin/workspaces"])

# ── Service singleton ──────────────────────────────────────────────────────
# Lazy-built so tests can monkeypatch ``_svc`` to a fixture.
_svc: WorkspaceService | None = None


def _service() -> WorkspaceService:
    global _svc
    if _svc is None:
        _svc = WorkspaceService()
    return _svc


def _author_email(claims: TokenClaims) -> str:
    return getattr(claims, "email", None) or getattr(claims, "sub", "unknown") or "unknown"


# ── Workspaces ─────────────────────────────────────────────────────────────


@router.get("", response_model=list[Workspace])
async def list_workspaces(
    _claims: TokenClaims = Depends(validate_token),
) -> list[Workspace]:
    return _service().list_workspaces()


@router.post("", response_model=Workspace, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    claims: TokenClaims = Depends(require_role("ask-admin")),
) -> Workspace:
    try:
        return _service().create_workspace(body, author_email=_author_email(claims))
    except SlugConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{id_or_slug}", response_model=Workspace)
async def get_workspace(
    id_or_slug: str,
    _claims: TokenClaims = Depends(validate_token),
) -> Workspace:
    try:
        return _service().get_workspace(id_or_slug)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {id_or_slug}") from exc


@router.patch("/{id_or_slug}", response_model=Workspace)
async def update_workspace(
    id_or_slug: str,
    body: WorkspaceUpdate,
    claims: TokenClaims = Depends(require_role("ask-admin")),
) -> Workspace:
    try:
        return _service().update_workspace(id_or_slug, body, author_email=_author_email(claims))
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {id_or_slug}") from exc
    except SlugConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{id_or_slug}", status_code=200)
async def delete_workspace(
    id_or_slug: str,
    _claims: TokenClaims = Depends(require_role("ask-admin")),
) -> dict[str, int]:
    """Cascade delete — workspace + all its business domains. Returns counts."""
    try:
        return _service().delete_workspace(id_or_slug)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {id_or_slug}") from exc


# ── Nested Business Domains ─────────────────────────────────────────────────


@router.get("/{id_or_slug}/business-domains", response_model=list[BusinessDomain])
async def list_business_domains(
    id_or_slug: str,
    _claims: TokenClaims = Depends(validate_token),
) -> list[BusinessDomain]:
    try:
        return _service().list_business_domains(id_or_slug)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {id_or_slug}") from exc


@router.post("/{id_or_slug}/business-domains", response_model=BusinessDomain, status_code=201)
async def create_business_domain(
    id_or_slug: str,
    body: BusinessDomainCreate,
    claims: TokenClaims = Depends(require_role("ask-admin")),
) -> BusinessDomain:
    try:
        created = _service().create_business_domain(
            id_or_slug, body, author_email=_author_email(claims)
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {id_or_slug}") from exc
    except SlugConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Seed/refresh the DP reverse index for the entities now in this BD.
    from .business_domains import sync_membership

    sync_membership(set(created.data_product_ids))
    return created


@router.get("/{id_or_slug}/entity-ids", response_model=list[str])
async def list_workspace_entity_ids(
    id_or_slug: str,
    _claims: TokenClaims = Depends(validate_token),
) -> list[str]:
    """Flat list of data product ids across all BDs — used for chat retrieval scope."""
    try:
        return _service().get_workspace_entity_ids(id_or_slug)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {id_or_slug}") from exc


# Note for the linter: BusinessDomainNotFoundError is imported here so /tests
# can re-raise it, but the workspace endpoints never raise it themselves
# (the BD-only endpoints in business_domains.py do).
_ = BusinessDomainNotFoundError
