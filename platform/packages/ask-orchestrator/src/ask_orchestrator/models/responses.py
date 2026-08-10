"""Outbound response models for the ASK Orchestrator HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .requests import Mode

MacroIntent = Literal[
    "SQL_EXECUTION",
    "SCHEMA_QUERY",
    "DOCS_QUERY",
    "ACTION_EXECUTION",  # reserved for Iter 7 — not emitted yet
]
# DASHBOARD_GEN was emitted by the legacy v1 graph and exposed temporarily
# in Iter 1. Iter 2 promotes the macro classifier into the orchestrator and
# folds DASHBOARD_GEN into SQL_EXECUTION (see classification/macro_classifier.py).


class Citation(BaseModel):
    """A single citation surfaced by DOCS / SCHEMA flows."""

    entity_id: str
    snippet: str = ""
    score: float = 0.0


class TokensBreakdown(BaseModel):
    """Per-request token breakdown captured by ask-llm-gateway's TokenTracker.
    Mirrors the dict returned by `TokenTracker.summary()` so the UI (and any
    external consumer like Watsonx) can show a phase-level expander without the
    orchestrator having to re-shape the data.

    Tokens only — cost is not tracked (priced differently per channel; the real
    bill lives in each provider's billing console).
    """

    total_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    by_phase: dict[str, dict[str, Any]] = Field(default_factory=dict)
    records: list[dict[str, Any]] = Field(default_factory=list)


class QueryResponse(BaseModel):
    answer: str = Field(
        ...,
        description="Natural-language answer rendered for the user.",
    )
    rows: list[dict[str, Any]] | None = Field(
        default=None,
        description="Tabular result set when the request executed SQL.",
    )
    sql: str | None = Field(
        default=None,
        description="SQL string produced by the pipeline, if applicable.",
    )
    macro_intent: MacroIntent = Field(
        ...,
        description=(
            "Macro intent detected for this request. Iter 1 bubbles this up "
            "from the legacy graph state; Iter 2 will move classification "
            "into the orchestrator."
        ),
    )
    mode_used: Mode = Field(
        ...,
        description="Agent mode that actually handled the request.",
    )
    trace_id: str = Field(
        ...,
        description="Correlation identifier for logs and observability.",
    )
    tokens_used: int | None = Field(
        default=None,
        description="Total LLM tokens consumed by this request, if tracked.",
    )
    citations: list[Citation] | None = Field(
        default=None,
        description=(
            "Structured citations supporting the answer. Populated for "
            "DOCS_QUERY (and SCHEMA_QUERY when retrieval surfaces them); "
            "None for SQL_EXECUTION."
        ),
    )
    tokens_breakdown: TokensBreakdown | None = Field(
        default=None,
        description=(
            "Per-phase token breakdown. None when the request did not "
            "execute through a TokenTracker-instrumented path."
        ),
    )


class ArtifactDataset(BaseModel):
    """One SQL query + its result rows, contributing to an artifact."""
    name: str = Field(..., description="Short label used as Excel sheet name.")
    sql: str = Field(..., description="SQL query executed.")
    rows: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = Field(default=None)


class ArtifactResponse(BaseModel):
    """Response for POST /v1/artifact — generated document with data context."""

    name: str = Field(..., description="Document name.")
    artifact_type: str = Field(..., description="Type of document generated.")
    format: str = Field(..., description="Layout style used.")
    content: str = Field(..., description="Full generated document in Markdown.")
    sql: str | None = Field(default=None, description="SQL used to retrieve data, if any.")
    rows: list[dict[str, Any]] | None = Field(
        default=None, description="Raw data rows used to populate the document."
    )
    data_error: str | None = Field(
        default=None, description="Error message if data retrieval failed, for UI display."
    )
    datasets: list[ArtifactDataset] | None = Field(
        default=None,
        description="All datasets (main + analytical sub-queries) used to generate the document.",
    )
    trace_id: str = Field(..., description="Correlation ID for logs.")
    tokens_used: int | None = Field(default=None)
    tokens_breakdown: TokensBreakdown | None = Field(default=None)


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    trace_id: str
