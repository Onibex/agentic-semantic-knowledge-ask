# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
OpenSearchKnowledgeGraphWriter — concrete impl of KnowledgeGraphWriter.

Iter 6 strategy: WRAP the production-tested legacy OpenSearchAskRepository
write methods rather than rewrite them. Same approach used by Iter 4's
reader. The legacy class still owns the index mappings, embedder hookup,
and bulk-write plumbing; this wrapper just exposes them through a typed
Protocol.

Once Iter 8/9 decommissions the legacy v1 ask_graph + the schema fallback,
the legacy class can be deleted and these wrappers become the data layer
themselves (rewrite at that point if needed).
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.errors import IngestionError
from ..domain.ports import KnowledgeGraphWriter

logger = logging.getLogger(__name__)


class OpenSearchKnowledgeGraphWriter(KnowledgeGraphWriter):
    """Adapter over OpenSearchAskRepository's save_* / delete_* methods."""

    def __init__(self, legacy_repo: Any) -> None:
        # legacy_repo is an OpenSearchAskRepository instance. Construction is
        # done by callers (orchestrator, admin API, the CLI) so
        # this package does not bind to the legacy class symbol.
        self._repo = legacy_repo

    # ── Save ────────────────────────────────────────────────────────────────
    def save_bronze(self, node: Any, yaml_content: str) -> dict[str, int]:
        try:
            return dict(self._repo.save_bronze_node(node, yaml_content) or {})
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            logger.warning("save_bronze failed: %s", exc)
            raise IngestionError(f"save_bronze failed: {exc}") from exc

    def save_silver(
        self, node: Any, yaml_content: str, embedder: Any | None = None
    ) -> dict[str, int]:
        try:
            return dict(self._repo.save_silver_node(node, yaml_content, embedder) or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("save_silver failed: %s", exc)
            raise IngestionError(f"save_silver failed: {exc}") from exc

    def save_gold(
        self, node: Any, yaml_content: str, embedder: Any | None = None
    ) -> dict[str, int]:
        try:
            return dict(self._repo.save_gold_node(node, yaml_content, embedder) or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("save_gold failed: %s", exc)
            raise IngestionError(f"save_gold failed: {exc}") from exc

    # ── Delete ──────────────────────────────────────────────────────────────
    def delete_entity(self, entity_id: str) -> dict[str, int]:
        try:
            return dict(self._repo.delete_entity_and_fields(entity_id) or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("delete_entity(%s) failed: %s", entity_id, exc)
            raise IngestionError(f"delete_entity({entity_id!r}) failed: {exc}") from exc
