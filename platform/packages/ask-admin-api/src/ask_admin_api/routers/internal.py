# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
``POST /v1/internal/reload`` — drop every cached singleton in the admin-api
process so the next request rebuilds them from a fresh
``config/settings.json``.

Mirrors the orchestrator's ``/v1/internal/reload`` endpoint by design — the
admin UI calls both after every Setup save so neither service holds stale
config.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/internal", tags=["internal"])


class ReloadResponse(BaseModel):
    service: str = "ask-admin-api"
    cleared: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace_id: str = ""


@router.post("/reload", response_model=ReloadResponse)
async def reload_singletons(
    user: TokenClaims = Depends(validate_token),
) -> ReloadResponse:
    trace_id = uuid.uuid4().hex
    cleared: list[str] = []
    errors: list[str] = []

    for scope_name, reset_fn in _reset_callables():
        try:
            cleared.extend(reset_fn())
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.exception(
                "reload scope failed", extra={"trace_id": trace_id, "scope": scope_name}
            )
            errors.append(f"{scope_name}: {exc}")

    logger.info(
        "config reload requested",
        extra={
            "trace_id": trace_id,
            "cleared": cleared,
            "errors": errors,
            "auth_email": user.email,
            "auth_issuer": user.issuer,
        },
    )
    return ReloadResponse(cleared=cleared, errors=errors, trace_id=trace_id)


def _reset_callables() -> list[tuple[str, Any]]:
    from . import dictionary as dict_router
    from . import docs as docs_router
    from . import embeddings as emb_router
    from . import yaml_ingestion as yaml_router

    return [
        ("dictionary_router", dict_router.reset_singletons),
        ("embeddings_router", emb_router.reset_singletons),
        ("yaml_ingestion_router", yaml_router.reset_singletons),
        ("docs_router", docs_router.reset_singletons),
    ]
