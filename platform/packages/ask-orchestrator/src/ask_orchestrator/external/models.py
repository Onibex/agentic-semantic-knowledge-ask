"""
Public API contract for /external/ask.

Deliberately decoupled from the chat-side ``QueryRequest``/``QueryResponse``:
external integrators (WatsonX, n8n, Zapier, custom B2B clients) need a
stable, minimal contract for "ask the agent" — not the chat-specific
fields like session_id or conversation_history. Keeping the models
disjoint lets the chat evolve without breaking integrators.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..models.requests import Environment, Mode
from ..models.responses import Citation, MacroIntent


class ExternalAskRequest(BaseModel):
    """Public input for the external ask endpoint.

    Minimal by design: only ``question`` and ``workspace_id`` are required.
    ``mode`` and ``env`` exist because they meaningfully change the answer
    pipeline; everything else (sessions, multi-turn history, debug flags) is
    intentionally chat-only.
    """

    question: str = Field(
        ...,
        min_length=1,
        description="Natural-language question for the ASK agent.",
        examples=["Top 10 customers by revenue this quarter"],
    )
    workspace_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Workspace UUID or slug. Required (Iter 1, Req #5): the agent "
            "answers only within the scope of one workspace's Data Products."
        ),
        examples=["sales-and-operations"],
    )
    mode: Mode = Field(
        default="smart",
        description=(
            "Agent mode. `smart` (default) is the catalog-driven Graph-RAG "
            "path — most stable for B2B integrations. `precise` and `flash` "
            "exist for chat-side experimentation."
        ),
    )
    env: Environment = Field(
        default="dev",
        description=(
            "Which published snapshot to query — the `dev` or `prod` Knowledge "
            "Graph indices. Default `dev` (safe choice; nothing reaches prod "
            "until explicitly promoted). Also drives which DB connection backs "
            "SQL execution (dev vs prod)."
        ),
    )


class ExternalWorkspace(BaseModel):
    """Public view of a workspace for the discovery endpoint.

    Minimal by design: just what a B2B client needs to pick the
    ``workspace_id`` (the ``slug``) to send to ``/external/ask``. Internal
    metadata (business domains, membership, audit fields) is intentionally
    excluded.
    """

    id: str = Field(..., description="Workspace UUID.")
    slug: str = Field(
        ...,
        description="Stable human-readable id — pass this as `workspace_id` to /external/ask.",
        examples=["sales-and-operations"],
    )
    name: str = Field(default="", description="Display name.")
    description: str = Field(default="", description="What the workspace is about.")


class ExternalAskResponse(BaseModel):
    """Public output for the external ask endpoint.

    Strict subset of the internal QueryResponse: keeps what an integrator
    consumes (answer, sql, rows, intent, trace, tokens, citations) and
    drops the chat-only fields (mode_used echo, internal tokens_breakdown
    detail).
    """

    answer: str = Field(
        ...,
        description="Natural-language answer suitable for direct display.",
    )
    sql: str | None = Field(
        default=None,
        description="SQL the agent generated, when the question hit the SQL pipeline.",
    )
    rows: list[dict[str, Any]] | None = Field(
        default=None,
        description="Tabular result rows when SQL was executed.",
    )
    macro_intent: MacroIntent = Field(
        ...,
        description="Macro intent the agent classified the question as.",
    )
    trace_id: str = Field(
        ...,
        description="Correlation id for cross-system log lookups.",
    )
    tokens_used: int | None = Field(
        default=None,
        description="Total LLM tokens consumed for this request, if tracked.",
    )
    citations: list[Citation] | None = Field(
        default=None,
        description="Structured citations for DOCS / SCHEMA answers.",
    )
