"""
``GET /external/workspaces`` — workspace discovery for B2B integrations.

Lets an external client (WatsonX, n8n, Zapier, custom) enumerate the
workspaces it can target before calling ``/external/ask``: each entry's
``slug`` is exactly the ``workspace_id`` that endpoint expects.

Reads ``ask-workspaces-v1`` directly through the orchestrator's
``WorkspaceScopeProvider`` (same OpenSearch index the admin-api owns) — no
HTTP hop to admin-api, no auth coupling between the two services.

Auth: OAuth2/OIDC bearer, same ``validate_token`` dependency as the chat
``/v1/query`` route (AUTH_MODE=xsuaa | keycloak). The dev dual-flag bypass
(ENVIRONMENT=local + DEV_BYPASS_AUTH=true) applies here too, so local Postman
testing needs no token.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ...auth.validator import TokenClaims, validate_token
from ...workspace_scope import get_scope_provider
from ..models import ExternalWorkspace

logger = logging.getLogger(__name__)

router = APIRouter(tags=["external"])


@router.get(
    "/workspaces",
    response_model=list[ExternalWorkspace],
    summary="List available workspaces",
    description=(
        "Enumerate the workspaces available to the agent. Use a returned "
        "`slug` as the `workspace_id` when calling /external/ask."
    ),
    operation_id="list_workspaces",
)
async def list_workspaces(
    _claims: TokenClaims = Depends(validate_token),
) -> list[ExternalWorkspace]:
    """Return the workspace catalog (id + slug + name + description)."""
    rows = get_scope_provider().list_workspaces()
    return [ExternalWorkspace(**row) for row in rows]
