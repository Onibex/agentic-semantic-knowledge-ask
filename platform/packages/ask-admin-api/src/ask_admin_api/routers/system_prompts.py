# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/prompts/*`` — editable system prompts.

Two endpoints, one prompt key (``enrichment``). Adding a second prompt is a
matter of declaring its default body in ``system_prompts_service._DEFAULT_PROMPTS``
and updating the ``PromptKey`` literal — no router change needed.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..application.system_prompts_service import (
    SystemPromptsService,
    get_standards_excerpt,
    is_known_key,
)
from ..auth.validator import TokenClaims, validate_token
from ..models.system_prompts import (
    PromptKey,
    SystemPromptResponse,
    SystemPromptUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/prompts", tags=["admin/prompts"])


_SERVICE: SystemPromptsService | None = None


def _service() -> SystemPromptsService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = SystemPromptsService()
    return _SERVICE


def reset_singletons() -> list[str]:
    """Hook for ``/v1/internal/reload`` — drop the cached service + standards."""
    global _SERVICE
    cleared: list[str] = []
    if _SERVICE is not None:
        _SERVICE = None
        cleared.append("system_prompts_service")
    from ..application.system_prompts_service import reload_standards_cache

    reload_standards_cache()
    cleared.append("standards_excerpt_cache")
    return cleared


def _validate_key(key: str) -> PromptKey:
    if not is_known_key(key):
        from ..application.system_prompts_service import known_prompt_keys

        raise HTTPException(
            status_code=404,
            detail=f"Unknown prompt key '{key}'. Valid keys: {', '.join(known_prompt_keys())}.",
        )
    return key  # type: ignore[return-value]


@router.get("/{key}", response_model=SystemPromptResponse)
async def get_prompt(
    key: str,
    _claims: TokenClaims = Depends(validate_token),
) -> SystemPromptResponse:
    """Return the active body + metadata for ``key``.

    ``is_default`` flags whether the body is the hardcoded fallback (true) or
    an admin-stored override (false). ``standards_excerpt`` is returned so
    the editor UI can show the standards reference next to the textarea.
    """
    valid_key = _validate_key(key)
    record = _service().get_record(valid_key)
    return SystemPromptResponse(
        key=valid_key,
        body=record.body,
        is_default=not record.updated_at,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
        standards_excerpt=get_standards_excerpt(),
    )


@router.put("/{key}", response_model=SystemPromptResponse)
async def put_prompt(
    key: str,
    body: SystemPromptUpdateRequest,
    claims: TokenClaims = Depends(validate_token),
) -> SystemPromptResponse:
    """Upsert (non-empty body) or reset to default (empty body) the prompt for ``key``."""
    valid_key = _validate_key(key)
    trace_id = uuid.uuid4().hex
    user = getattr(claims, "email", None) or "anonymous"

    if not body.body.strip():
        default_body = _service().reset_to_default(valid_key)
        logger.info("[%s] prompts reset key=%s user=%s", trace_id, valid_key, user)
        return SystemPromptResponse(
            key=valid_key,
            body=default_body,
            is_default=True,
            standards_excerpt=get_standards_excerpt(),
        )

    record = _service().upsert(valid_key, body.body, user)
    logger.info(
        "[%s] prompts upsert key=%s user=%s bytes=%d",
        trace_id,
        valid_key,
        user,
        len(body.body),
    )
    return SystemPromptResponse(
        key=valid_key,
        body=record.body,
        is_default=False,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
        standards_excerpt=get_standards_excerpt(),
    )
