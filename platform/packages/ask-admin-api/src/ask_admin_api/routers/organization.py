# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/organization`` — singleton organization profile.

Backs Req #3 of REQUIREMENTS_NEW_FEATURES.md. One deploy = one customer
(per locked decision), so there's exactly one document. ``GET`` always
returns something (defaults to a blank record); ``PUT`` upserts.

The orchestrator consumes this through the same service to inject
``company_name`` / ``sap_version`` / ``core_bases`` into the agent's
system prompt — wired in a separate task (Iter1.C3).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ..application.workspace_service import WorkspaceService
from ..auth.validator import TokenClaims, validate_token
from ..models.workspaces import Organization, OrganizationUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/organization", tags=["admin/organization"])

_svc: WorkspaceService | None = None


def _service() -> WorkspaceService:
    global _svc
    if _svc is None:
        _svc = WorkspaceService()
    return _svc


def _author_email(claims: TokenClaims) -> str:
    return getattr(claims, "email", None) or getattr(claims, "sub", "unknown") or "unknown"


@router.get("", response_model=Organization)
async def get_organization(
    _claims: TokenClaims = Depends(validate_token),
) -> Organization:
    return _service().get_organization()


@router.put("", response_model=Organization)
async def upsert_organization(
    body: OrganizationUpdate,
    claims: TokenClaims = Depends(validate_token),
) -> Organization:
    return _service().upsert_organization(body, author_email=_author_email(claims))
