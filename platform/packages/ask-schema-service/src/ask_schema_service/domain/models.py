# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Domain models for Schema queries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchemaQuery:
    """Inputs for one schema-question call.

    ``allowed_entity_ids`` (BACKLOG A/D1 — workspace scope): ``None`` =
    unscoped (whole registry, legacy/CLI callers); a list hard-restricts the
    retrieval universe to those entity ids (``[]`` = match nothing). The
    orchestrator passes the SCHEMA-plane scope — chat membership widened with
    ``composed_of`` bronzes — so Bronze schema questions stay answerable.
    """

    question: str
    allowed_entity_ids: list[str] | None = None


@dataclass(frozen=True)
class SchemaResponse:
    """Outcome of a schema query.

    Iter 5 keeps `answer` as a single rendered string (matching the legacy
    `SchemaCatalogService.resolve_schema(...)` return shape). Future iterations
    may add structured fields (matched_entity_id, layer_hint, etc.) but for
    now the orchestrator just surfaces `answer` in QueryResponse.
    """

    answer: str
    error: str | None = None
