# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Intent Resolution result contract.

Iter 2 note: strategies are wrappers over the legacy v1/v2/Flash pipelines
and therefore still produce the FULL response (SQL + rows + answer). Iter 3
splits the SQL phase out — at that point this dataclass narrows to just the
intent-resolution outputs (yamls + ir + edges + disambiguation), and a
separate SqlGenerationResult covers the rest.

The `plan` field is intentionally typed as `dict[str, Any]` because the v1
SemanticPlanIR and the v2 SemanticPlanIRv2 don't share a schema yet. The
adapter normalizes whatever the legacy graph state contains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Mode = Literal["flash", "precise", "smart"]
DisambiguationLevel = Literal["L0", "L1", "L2", "L3"]


@dataclass(frozen=True)
class Disambiguation:
    """What the semantic dictionary made of a question it had to look up.

    No strategy writes text for the user here, and only the SQL generator
    decides whether to ask: in the chat it may ask the user one question and
    answer with the reply (human in the loop, a plain chat message, no state
    kept on the server); everywhere else it picks a reading and the answer says
    so. This supersedes ADR-014 ("exit with a message", no HiTL).

      - L2: the terms matched several modules. The plan follows the top one and
        the pipeline goes on; `options` are the other readings
        ("MODULE: label, label"), handed to the SQL generator to weigh.
      - L3: nothing in the message maps to the semantic layer. The turn stops
        before SQL generation and the orchestrator answers in the user's
        language.
    `message` is kept empty.
    """

    level: DisambiguationLevel
    message: str
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolutionTrace:
    """Observability metadata. Populated best-effort by each strategy."""

    strategy: str
    duration_ms: int | None = None
    tokens_used: int | None = None
    confidence: float | None = None
    notes: str | None = None


@dataclass(frozen=True)
class IntentResolutionResult:
    """Outcome of running one strategy against a user question.

    Iter 3 split decision (see ITERATION_3_PLAN.md Q1)
    ────────────────────────────────────────────────────
    - Precise/Smart strategies STOP at IR resolution: `plan`, `yamls`, `edges`
      are populated; `sql`, `rows`, `answer` stay None. The orchestrator
      then chains SqlGenerationService.

    - Flash bypasses the chain (chunk RAG is a single LLM call from question
      to SQL). It populates `sql`, `rows`, `answer` itself; `plan`, `yamls`,
      `edges` are empty. The orchestrator detects `result.sql is not None`
      and skips SqlGenerationService for Flash.

    Stable fields (Precise + Smart):
      - plan: serialized SemanticPlanIR (v1) or SemanticPlanIRv2 (v2)
      - yamls: resolved entities with raw_yaml
      - edges: JOIN edges, dialect-agnostic
      - disambiguation: what the dictionary made of the question (see
        Disambiguation: L2 goes on with other readings, L3 stops the turn)
      - error: non-fatal failure surfaced to the caller
      - trace: observability

    Flash-only fields (Precise/Smart leave them None/empty):
      - sql: generated SQL string
      - rows: executed result set
      - answer: business-friendly natural language answer
    """

    plan: dict[str, Any]
    yamls: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    disambiguation: Disambiguation | None
    error: str | None
    trace: ResolutionTrace
    # Flash-only fields. See class docstring.
    sql: str | None = None
    rows: list[dict[str, Any]] | None = None
    answer: str = ""
