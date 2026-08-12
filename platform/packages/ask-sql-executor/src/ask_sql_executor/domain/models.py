"""Domain models for SQL execution + result formatting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Supported execution backends. The execution registry
# (infrastructure.registry) is the runtime source of truth; this Literal
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
    "presto",
]


@dataclass(frozen=True)
class ExecutionRequest:
    """Inputs to run one SQL statement."""

    sql: str
    db_type: DbType
    db_config: dict[str, Any]
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class ExecutionResult:
    """Raw outcome of a SQL execution.

    Either rows is populated (success) or error is populated (failure) — they
    are mutually exclusive in practice but both present on the dataclass for a
    flat shape.
    """

    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    row_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class FormattedResult:
    """Outcome of running execute → format pipeline.

    `rows_dict` is the row-oriented projection (one dict per row keyed by
    column name) ready to ship in QueryResponse.rows. `answer` is the
    business-friendly NL summary built either from the rows or from the
    no-results helper.
    """

    sql: str
    rows_dict: list[dict[str, Any]]
    answer: str
    error: str | None = None
    row_count: int = 0
