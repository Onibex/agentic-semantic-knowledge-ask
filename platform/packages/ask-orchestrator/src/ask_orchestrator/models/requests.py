# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Inbound request models for the ASK Orchestrator HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# External contract naming. Internal UI labels (e.g. "Chunk (RAG)", "v1
# (Semi-Det)", "v2 (Graph RAG)") are mapped to these on the client side by
# the chat SPA. This separation lets us evolve the UI labels independently
# from the API contract.
Mode = Literal["flash", "precise", "smart"]

# Environments mirror the publish targets owned by admin-api (UX_CHANGES
# audit Q6). ``dev`` is the safe default — every entity goes through
# Publish-to-dev first per the lifecycle gate, so a chat session against
# a workspace whose entities are still in In Review still gets a useful
# answer from the most recent dev snapshot.
Environment = Literal["dev", "prod"]


class QueryRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        description="User's question in natural language.",
    )
    workspace_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Workspace UUID or slug. Required (Iter 1, Req #5): the agent only "
            "answers within the scope of one workspace's Data Products — no "
            "cross-workspace queries. Use /v1/admin/workspaces to discover."
        ),
    )
    mode: Mode = Field(
        default="precise",
        description="Agent mode for SQL queries.",
    )
    env: Environment = Field(
        default="dev",
        description=(
            "Which published snapshot to query — the ``dev`` or ``prod`` "
            "Knowledge Graph indices owned by admin-api's publish flow. "
            "Default ``dev`` (safe choice; nothing reaches prod until "
            "explicitly promoted via the deployment panel). Also drives "
            "which DB connection backs SQL execution (HANA dev vs prod)."
        ),
    )
    session_id: str | None = Field(
        default=None,
        description="Conversation session identifier (used for graph thread_id).",
    )
    conversation_history: list[dict[str, Any]] | None = Field(
        default=None,
        description="Prior conversation turns for context.",
    )


class ArtifactRequest(BaseModel):
    name: str = Field(
        default="Untitled Document",
        description="Display name for the generated document.",
    )
    artifact_type: str = Field(
        ...,
        description="Type of document: sales_report, inventory_report, executive_summary, etc.",
    )
    format: str = Field(
        default="detailed_report",
        description="Layout style: executive_brief, detailed_report, data_tables, proposal_format.",
    )
    purpose: str = Field(
        ...,
        description="Intended audience and use case for the document.",
    )
    data_focus: str = Field(
        ...,
        description="Natural language description of the data to include (drives the SQL query).",
    )
    mode: Mode = Field(
        default="smart",
        description="Agent mode used to retrieve underlying data.",
    )
    sql_override: str | None = Field(
        default=None,
        description="Pre-built SQL to execute directly, bypassing the query pipeline (used for artifact refreshes).",
    )
    workspace_id: str = Field(
        default="",
        description="Workspace slug to scope the data retrieval pipeline.",
    )
    env: Environment = Field(
        default="dev",
        description="Publish snapshot to query: 'dev' or 'prod'.",
    )
