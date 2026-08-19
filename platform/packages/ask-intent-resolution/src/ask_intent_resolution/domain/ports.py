# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Inbound and outbound ports for Intent Resolution.

Inbound:
  - IntentResolver: the protocol the orchestrator depends on. The
    `ResolveIntentUseCase` is its concrete implementation.

Outbound (declared but NOT consumed by Iter 2 strategies):
  - KnowledgeGraphPort: shape that strategies will use in Iter 3 once they
    stop calling legacy infrastructure directly.
  - LLMPort: same, for LLM access.
  Iter 2 strategies still depend on legacy modules directly (wrap-not-split
  per the iteration plan). The ports are checked-in early so consumers can
  start building against the interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .result import IntentResolutionResult, Mode


@dataclass(frozen=True)
class ResolutionRequest:
    """Inputs for a single intent-resolution call."""

    question: str
    mode: Mode
    session_id: str | None = None
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    # Workspace-scoped entity allowlist (Iter 1, Req #5). When provided the
    # smart strategy filters its catalog to this set; None falls back to the
    # legacy ``pipeline_v2.active_profile`` lookup in settings.json (kept
    # temporarily for batch / CLI callers that don't pass a workspace).
    #
    # CONTRACT — three-valued, and every consumer MUST branch on ``is None``,
    # never on truthiness:
    #   * ``None``  → UNSCOPED. No workspace context (CLI / batch). Whole registry.
    #   * ``[]``    → EMPTY SCOPE. A real workspace whose data products resolve to
    #                 zero entities answerable in this env → return NOTHING.
    #   * ``[...]`` → restrict the candidate universe to exactly these ids.
    # The ``[]`` case is produced by env-gated scope resolution (Option B): a
    # workspace's data-product membership intersected with the entities actually
    # published to the requested env. Treating ``[]`` as falsy (``if allowed_ids:``)
    # silently opens the WHOLE registry — the opposite of the gate — so it is a leak.
    allowed_entity_ids: list[str] | None = None
    # Organization context snippet (Iter 1, Req #3). Pre-rendered text the
    # orchestrator pulls from ``ask-organization-v1`` and passes here so
    # prompt builders can prepend it to their system prompts. None when the
    # admin hasn't filled the Organization form yet.
    organization_context: str | None = None
    # Publish environment to read from (UX_CHANGES audit CH-2 / Iter 4 read
    # cutover). ``'dev'`` / ``'prod'`` map to OpenSearch indices
    # ``ask-*-dev`` / ``ask-*-prod``. ``None`` means the strategy uses the
    # legacy un-suffixed indices (back-compat shim from Iter 2). The
    # orchestrator should always pass a concrete env; ``None`` survives
    # only for batch / CLI callers built before the cutover.
    env: str | None = None


class IntentResolver(Protocol):
    """The single inbound contract.

    Concrete implementation: ResolveIntentUseCase. Strategies plug INTO
    the use case rather than implementing this Protocol themselves — the
    use case is responsible for picking the right strategy per `mode` and
    normalizing its output.
    """

    def resolve(self, request: ResolutionRequest) -> IntentResolutionResult: ...


# ─────────────────────────────────────────────────────────────────────────────
# Outbound ports — declared for Iter 3 consumers, not used by Iter 2 strategies.
# ─────────────────────────────────────────────────────────────────────────────
class KnowledgeGraphPort(Protocol):
    """Read access to the ASK knowledge graph (Iter 4 will own the impl)."""

    def search_entities(self, query: str, top_k: int = 5) -> list[dict[str, Any]]: ...
    def get_entity(self, entity_id: str) -> dict[str, Any] | None: ...
    def get_edges_between(
        self, source_ids: list[str], target_ids: list[str]
    ) -> list[dict[str, Any]]: ...


class LLMPort(Protocol):
    """LLM access (Iter 4 unifies this through ask-llm-gateway)."""

    def chat(self, prompt: str, **kwargs: Any) -> str: ...
    def embed(self, text: str) -> list[float]: ...
