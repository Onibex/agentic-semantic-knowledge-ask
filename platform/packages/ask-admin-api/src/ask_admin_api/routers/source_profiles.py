"""``/v1/admin/source-profiles`` — code-defined source-system profiles.

Read-only list of the ``SourceSystemProfile``s the EntityDeriver / DDL importer
know about (``s4h`` / ``ecc`` / ``generic`` / ``salesforce`` / ``odoo``). Drives
the DDL+AI form's source-system selector so the UI never hardcodes the list and
stays in sync with the backend (Phase C2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.validator import TokenClaims, validate_token

router = APIRouter(prefix="/v1/admin/source-profiles", tags=["admin/source-profiles"])


@router.get("", response_model=list[dict])
async def list_source_profiles(
    _claims: TokenClaims = Depends(validate_token),
) -> list[dict]:
    """Return ``[{key, label}]`` for every code-defined source-system profile."""
    from ask_knowledge_graph.domain.source_profiles import list_profiles

    return list_profiles()
