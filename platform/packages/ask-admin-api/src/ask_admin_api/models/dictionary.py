# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Request / response models for ``/v1/admin/dictionary``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DictionaryEntry(BaseModel):
    """One row in the semantic dictionary (field/metric/phrase mapping).

    Liberal schema by design: the typed-package ``DictionaryWriter`` accepts
    any dict and enriches with embeddings on write. Different mapping types
    (field/metric/phrase) populate different optional fields.
    """

    type: str = Field(
        ..., description="metric | dimension | filter | identifier | timestamp | phrase"
    )
    canonical_label: str
    technical_name: str = ""
    table: str = ""
    module: str
    source_system: str = "s4h"
    synonyms: str = ""
    context_clues: str = ""
    disambiguation_hint: str = ""
    entity_id: str | None = None
    description: str = ""
    # Schema v2 — value-level enrichments (consumed by FreeformSqlGenerator).
    examples: str = ""
    value_synonyms: str = ""
    is_preferred_id: bool = False


class DictionaryUpsertResponse(BaseModel):
    success: bool
    message: str = ""


class DictionaryDeleteResponse(BaseModel):
    success: bool
    message: str = ""


class DictionaryListResponse(BaseModel):
    entries: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Raw dict shape from the DictionaryWriter — kept loose because the "
            "store may include schema v2 fields (examples list, value_synonyms "
            "dict) that don't map cleanly to a fixed Pydantic model."
        ),
    )
