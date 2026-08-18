# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/ingest-config`` — effective, deployment-level ingestion config.

Read-only. Returns the RESOLVED values (env override included), unlike
``/v1/admin/config`` which reflects only the raw ``settings.json`` file.
Drives the Manual-entity form's field derivation so ASK Studio mints the same
published column names the SAP JSON parser does.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.validator import TokenClaims, validate_token

router = APIRouter(prefix="/v1/admin/ingest-config", tags=["admin/ingest-config"])


@router.get("", response_model=dict)
async def get_ingest_config(
    _claims: TokenClaims = Depends(validate_token),
) -> dict:
    """Return ``{column_naming}`` as resolved for this deployment."""
    from ask_knowledge_graph.infrastructure.naming_config import resolve_column_naming_mode

    return {"column_naming": resolve_column_naming_mode().value}
