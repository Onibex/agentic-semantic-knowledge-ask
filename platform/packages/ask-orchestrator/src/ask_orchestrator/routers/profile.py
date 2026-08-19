# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``POST /v1/profile`` — synthesize a user analytics profile from their chat
history.

Auth: same XSUAA dependency as ``/v1/query``. Errors map to HTTP 500 with the
standard ``ErrorResponse`` shape so the chat UI can surface them uniformly.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth.validator import TokenClaims, validate_token
from ..models.profile import ProfileBuildRequest, ProfileBuildResponse
from ..models.responses import ErrorResponse
from ..profile.builder import ProfileBuilder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["profile"])


_builder_lock = threading.Lock()
_builder_singleton: Any = None


def reset_singletons() -> list[str]:
    """Drop the cached profile builder so the next request rebuilds the LLM
    bundle from a fresh ``settings.json``."""
    global _builder_singleton
    cleared: list[str] = []
    if _builder_singleton is not None:
        cleared.append("profile_builder_router")
    _builder_singleton = None
    return cleared


def _get_builder() -> ProfileBuilder:
    global _builder_singleton
    if _builder_singleton is not None:
        return _builder_singleton
    with _builder_lock:
        if _builder_singleton is not None:
            return _builder_singleton
        _builder_singleton = ProfileBuilder()
        return _builder_singleton


@router.post(
    "/profile",
    response_model=ProfileBuildResponse,
    responses={500: {"model": ErrorResponse}},
)
def build_profile(
    req: ProfileBuildRequest,
    claims: TokenClaims = Depends(validate_token),
) -> ProfileBuildResponse:
    """Build a fresh profile from the supplied chat history.

    Sync `def` so FastAPI dispatches to the Starlette thread pool. The builder
    makes blocking LLM calls; keeping this `async def` would serialize requests
    on the event loop.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "profile build received",
        extra={
            "trace_id": trace_id,
            "user_id": req.user_id,
            "msg_count": len(req.messages),
            "auth_email": claims.email,
            "auth_issuer": claims.issuer,
        },
    )
    try:
        return _get_builder().build(
            user_id=req.user_id,
            display_name=req.display_name,
            role=req.role,
            messages=req.messages,
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("profile build failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error_code="PROFILE_BUILD_ERROR",
                message=str(exc),
                trace_id=trace_id,
            ).model_dump(),
        )
