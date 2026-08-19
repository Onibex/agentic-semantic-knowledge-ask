# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Domain models for SQL Generation.

The shapes mirror the legacy FreeformSQLGeneratorService.generate() signature
so the port in application/freeform_generator.py can be near-mechanical, then
the orchestrator builds requests cleanly from IntentResolutionResult instead
of from the loose kwargs the legacy service accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Supported SQL dialects. The dialect-prompt registry
# (application.prompts.registry) is the runtime source of truth; this Literal
# documents the set + keeps type-checking. Lite multi-DB, 2026-07.
DbType = Literal[
    "hana",
    "postgresql",
    "snowflake",
    "databricks",
    "clickhouse",
    "sqlserver",
    "db2",
    "bigquery",
    "fabric",
]


@dataclass(frozen=True)
class ScopeAudit:
    """Result of running the SQL scope validator over a generated query."""

    ok: bool
    out_of_scope: list[str] = field(default_factory=list)
    in_scope: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SqlGenerationRequest:
    """Inputs for one SQL generation call.

    `yamls`, `edges` and `resolved_paths` come from the upstream
    IntentResolutionResult. `ir_hints` is the serialized SemanticPlanIR.
    Optional fields default to "no extra context".
    """

    question: str
    yamls: list[str]
    db_type: DbType
    ir_hints: dict[str, Any] = field(default_factory=dict)
    edges: list[Any] = field(default_factory=list)
    resolved_paths: dict[str, Any] = field(default_factory=dict)
    field_enrichments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    glossary: str = ""
    conversation_history: str = ""
    user_system_prompt: str = ""
    pg_sap_rules: str = ""
    connectivity: dict[str, Any] = field(default_factory=dict)
    validate_scope: bool = True
    max_scope_retries: int = 1
    context_expansion_enabled: bool = False
    hana_schema: str = ""


@dataclass(frozen=True)
class SqlGenerationResult:
    """Outcome of a single SQL generation request.

    `error` and `sql` are mutually exclusive in the happy path:
      - sql populated, error=None     → success
      - sql=None,    error populated  → generator could not produce SQL
    `scope_warning` is populated when the scope auditor failed but we still
    return the SQL (legacy behavior — non-fatal).
    """

    sql: str | None
    error: str | None
    scope_audit: ScopeAudit | None = None
    scope_warning: str | None = None
    need_more_context: bool = False
    table_name: str | None = None
    retry_count: int = 0
    tokens_used: int | None = None
    raw_response: str | None = None
