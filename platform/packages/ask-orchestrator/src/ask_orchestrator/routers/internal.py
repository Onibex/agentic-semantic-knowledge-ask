"""
``POST /v1/internal/reload`` — drop every cached singleton in the
orchestrator process so the next request rebuilds them from a fresh
``config/settings.json``.

Why
───
``settings.json`` is a mutable file shared across services via a PVC mount.
The admin plane edits it freely, but the orchestrator caches
heavy bundles (LLMs, vectorstore connections, dictionary writers) at first
use — so without an explicit invalidation the new config never reaches
runtime. This endpoint is the invalidation hook the UI calls after every
save (Plan QW1, 2026-05-08).

Scope
─────
Internal control plane — like ``/v1/health``. Honors the same XSUAA
dependency as ``/v1/query`` so it can't be abused publicly, but the
operation is local to this process: no I/O against OpenSearch / DBs / SAP
AI Core happens here. The next user request pays the rebuild cost.
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
    """What the reload actually cleared, plus any non-fatal error per scope."""

    service: str = "ask-orchestrator"
    cleared: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace_id: str = ""


@router.post("/reload", response_model=ReloadResponse)
async def reload_singletons(
    claims: TokenClaims = Depends(validate_token),
) -> ReloadResponse:
    trace_id = uuid.uuid4().hex
    cleared: list[str] = []
    errors: list[str] = []

    # Each reset returns a list of singleton names actually dropped — we
    # collect them all into one flat list for the response. Errors in one
    # scope must not block the others.
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
            "auth_email": claims.email,
            "auth_issuer": claims.issuer,
        },
    )
    return ReloadResponse(cleared=cleared, errors=errors, trace_id=trace_id)


def _reset_callables() -> list[tuple[str, Any]]:
    """Lazy-resolve every reset hook to keep this router cheap to import."""
    from ask_intent_resolution.application.resolve_intent_use_case import (
        reset_default_use_case,
    )

    from ..classification.macro_classifier import MacroIntentClassifier
    from ..profile.builder import ProfileBuilder
    from . import profile as profile_router
    from . import query as query_router

    def _macro_reset() -> list[str]:
        return ["macro_classifier_chain"] if MacroIntentClassifier.reset() else []

    def _profile_builder_reset() -> list[str]:
        return ["profile_builder_llm"] if ProfileBuilder.reset() else []

    def _secrets_reset() -> list[str]:
        # Drop the SecretsProvider cache so the next build_llm / build_embedder
        # picks up writes from /v1/admin/secrets without waiting for the 60s TTL.
        from ask_llm_gateway.infrastructure.secrets import get_secrets_provider

        get_secrets_provider().invalidate()
        return ["secrets_provider_cache"]

    return [
        ("query_router", query_router.reset_singletons),
        ("profile_router", profile_router.reset_singletons),
        ("macro_classifier", _macro_reset),
        ("profile_builder", _profile_builder_reset),
        ("intent_resolution_use_case", reset_default_use_case),
        ("secrets_provider", _secrets_reset),
    ]
