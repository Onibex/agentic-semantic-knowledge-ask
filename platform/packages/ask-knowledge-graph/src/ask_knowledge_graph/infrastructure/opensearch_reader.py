# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
OpenSearchKnowledgeGraphReader — concrete impl of KnowledgeGraphReader.

Iter 4 strategy: WRAP the production-tested legacy OpenSearchAskRepository
read methods rather than rewrite them. The legacy class still owns the
full read+write surface and the ingestion code keeps using it directly
until Iter 6 extracts the write side.

The wrapper exists so:
  - The strategies and orchestrator depend on the typed Protocol, not on
    a class with 11 mixed read/write methods + a public `client` attribute.
  - mget_raw_yaml replaces direct `os_repo.client.mget(...)` calls.
  - The shape of returned records is a stable `dict[str, Any]` (Iter 5+
    promotes to dataclasses without breaking the Protocol).
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.errors import IndexUnavailableError
from ..domain.models import EntityRecord
from ..domain.ports import KnowledgeGraphReader

logger = logging.getLogger(__name__)

# Fallback only. The authoritative entity-index name lives on the wrapped
# repository (``legacy_repo.INDEX_ENTITY``) so an env-suffixed repo (Iter 2)
# automatically reads from its own ``ask-entity-registry-v1-{env}`` index.
ENTITY_INDEX = "ask-entity-registry-v1"


class OpenSearchKnowledgeGraphReader(KnowledgeGraphReader):
    """Adapter over OpenSearchAskRepository (legacy class kept as the data layer)."""

    def __init__(self, legacy_repo: Any) -> None:
        # legacy_repo is an OpenSearchAskRepository instance. We don't import
        # it here to keep the package importable in isolation.
        self._repo = legacy_repo

    # ── Entity lookups ──────────────────────────────────────────────────────
    def get_entity_by_id(self, entity_id: str) -> EntityRecord | None:
        try:
            return self._repo.get_entity_by_id(entity_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_entity_by_id(%s) failed: %s", entity_id, exc)
            return None

    def get_lightweight_entities(self) -> list[EntityRecord]:
        return list(self._repo.get_lightweight_entities() or [])

    def mget_raw_yaml(self, entity_ids: list[str]) -> dict[str, str]:
        if not entity_ids:
            return {}
        index = getattr(self._repo, "INDEX_ENTITY", ENTITY_INDEX)
        try:
            resp = self._repo.client.mget(
                index=index,
                body={"ids": list(entity_ids)},
                _source=["id", "raw_yaml"],
            )
        except Exception as exc:  # noqa: BLE001
            raise IndexUnavailableError(f"mget against {index} failed: {exc}") from exc

        out: dict[str, str] = {}
        for doc in resp.get("docs") or []:
            if not doc.get("found"):
                continue
            raw = (doc.get("_source") or {}).get("raw_yaml")
            doc_id = doc.get("_id")
            if doc_id and raw:
                out[doc_id] = raw
        return out

    # ── Search ──────────────────────────────────────────────────────────────
    def search_hybrid_rrf(
        self,
        text_query: str,
        vector_query: list[float],
        size: int = 10,
        layers: list[str] | None = None,
    ) -> list[EntityRecord]:
        return list(
            self._repo.search_hybrid_rrf(
                text_query=text_query,
                vector_query=vector_query,
                size=size,
                layers=layers,
            )
            or []
        )

    def search_gold_rescue(self, text_query: str, size: int = 5) -> list[EntityRecord]:
        return list(self._repo.search_gold_rescue(text_query, size=size) or [])

    def search_best_field(self, text_query: str, vector_query: list[float]) -> dict[str, Any]:
        return self._repo.search_best_field(text_query, vector_query) or {}

    # ── Edges ───────────────────────────────────────────────────────────────
    def get_all_edges(self) -> list[dict[str, Any]]:
        return list(self._repo.get_all_edges() or [])
