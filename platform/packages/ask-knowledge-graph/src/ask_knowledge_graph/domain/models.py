# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Domain records returned by the KnowledgeGraphReader.

These are intentionally `dict[str, Any]`-friendly aliases right now: the
underlying OpenSearch documents have rich, evolving shapes (raw_yaml
embedded, metadata variable across layers) and forcing tight schemas in
Iter 4 would multiply the migration cost. Iter 5+ may tighten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

# Each is a dict shaped like the legacy `_source` payload from OpenSearch,
# with at least an `id` key. Iter 5+ promotes them to dataclasses.
EntityRecord: TypeAlias = dict[str, Any]
FieldRecord: TypeAlias = dict[str, Any]
EdgeRecord: TypeAlias = dict[str, Any]
DictionaryTerm: TypeAlias = dict[str, Any]


# ─────────────────────────────────────────────────────────────────────────────
# Iter 6 — write side
# ─────────────────────────────────────────────────────────────────────────────
EntityLayer: TypeAlias = Literal["bronze", "silver", "gold"]


@dataclass(frozen=True)
class IngestionRequest:
    """Inputs for one YAML ingestion call.

    The ingestion service handles the parsing internally — callers just
    pass the YAML text + an optional explicit layer override.
    """

    yaml_content: str
    layer_override: EntityLayer | None = None


@dataclass(frozen=True)
class IngestionResult:
    """Stats returned from an ingest / delete call."""

    entity_id: str | None = None
    layer: EntityLayer | None = None
    entities_indexed: int = 0
    fields_indexed: int = 0
    edges_indexed: int = 0
    error: str | None = None
    raw_stats: dict[str, Any] = field(default_factory=dict)
