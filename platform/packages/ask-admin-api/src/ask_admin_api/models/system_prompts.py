"""Pydantic models for ``/v1/admin/prompts/*``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PromptKey = Literal["enrichment"]


class SystemPromptResponse(BaseModel):
    """Body for ``GET /v1/admin/prompts/{key}``.

    ``is_default`` is true when the active body is the hardcoded fallback
    (no override doc stored). ``standards_excerpt`` is included so the SPA
    editor can show the read-only reference an admin needs while editing.
    """

    key: PromptKey
    body: str
    is_default: bool
    updated_at: str = ""
    updated_by: str = ""
    standards_excerpt: str = Field(
        default="",
        description="Read-only Semantic Layer Standards subset shown alongside the editor.",
    )


class SystemPromptUpdateRequest(BaseModel):
    """Body for ``PUT /v1/admin/prompts/{key}``. Empty body → reset to default."""

    body: str = Field(
        ...,
        description=(
            "Full prompt body. Send an empty string to clear the override and "
            "fall back to the hardcoded default."
        ),
    )
