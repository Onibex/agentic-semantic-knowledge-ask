# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
``POST /external/ask`` — single public entrypoint for B2B integrations.

Adapts the public ``ExternalAskRequest`` to the internal ``QueryRequest``,
runs ``run_query_pipeline`` (the same pipeline the chat /v1/query uses),
and projects the result back to the public ``ExternalAskResponse``.

Auth: OAuth2/OIDC bearer, the same ``validate_token`` dependency as the chat
``/v1/query`` route (AUTH_MODE=xsuaa | keycloak). The dev dual-flag bypass
(ENVIRONMENT=local + DEV_BYPASS_AUTH=true) applies here too, so local Postman
testing needs no token; production fails closed without a valid bearer.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ...auth.validator import TokenClaims, validate_token
from ...models.requests import QueryRequest
from ...routers.query import run_query_pipeline
from ..models import ExternalAskRequest, ExternalAskResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["external"])


@router.post(
    "/ask",
    response_model=ExternalAskResponse,
    summary="Ask the ASK agent",
    description=(
        "Send a natural-language question to the agent. Returns the "
        "natural-language answer plus the SQL + rows when applicable, the "
        "detected macro intent, and a trace id for log correlation."
    ),
    operation_id="ask_agent",
)
async def ask(
    req: ExternalAskRequest,
    claims: TokenClaims = Depends(validate_token),
) -> ExternalAskResponse:
    """Single public entrypoint — same pipeline as the chat /v1/query
    route, with a stripped-down contract."""
    internal_req = QueryRequest(
        question=req.question,
        workspace_id=req.workspace_id,
        mode=req.mode,
        env=req.env,
        # Chat-only fields stay None for external clients.
        session_id=None,
        conversation_history=None,
    )
    # Identity for log/audit correlation comes from the validated bearer.
    user = {"email": claims.email, "bypass": False, "roles": claims.roles}
    internal_resp = run_query_pipeline(internal_req, user)

    return ExternalAskResponse(
        answer=internal_resp.answer,
        sql=internal_resp.sql,
        rows=internal_resp.rows,
        macro_intent=internal_resp.macro_intent,
        trace_id=internal_resp.trace_id,
        tokens_used=internal_resp.tokens_used,
        citations=internal_resp.citations,
    )
