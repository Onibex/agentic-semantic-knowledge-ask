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
    """A user-facing disambiguation prompt that pauses the pipeline.

    Iter 2 keeps the legacy "exit with message" semantics (per ADR-014 — no
    HiTL). When `message` is non-empty, the strategy short-circuits before
    SQL generation.
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
      - disambiguation: short-circuit signal (L0-L3 from the dictionary)
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
