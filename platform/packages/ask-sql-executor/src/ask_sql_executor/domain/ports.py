"""Ports for SQL execution.

Inbound:
  SqlExecutor — the contract the orchestrator depends on. Concrete impl is
  application.executor_service.SqlExecutorService.

Outbound:
  ResultFormatter — the LLM-backed formatter. Iter 4 ships a concrete impl
  in application.result_formatter; future iterations may swap it for a
  template-based formatter that does not need an LLM.
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import ExecutionRequest, ExecutionResult, FormattedResult


class SqlExecutor(Protocol):
    """Inbound — orchestrator-facing."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run the SQL and return rows as tuples (driver-native shape)."""
        ...

    def execute_and_format(self, request: ExecutionRequest, *, question: str) -> FormattedResult:
        """Run + format. Used by the orchestrator's SQL_EXECUTION branch."""
        ...


class ResultFormatter(Protocol):
    """Outbound — pluggable so the orchestrator can swap LLMs / template engines."""

    def format_rows(
        self,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        question: str,
    ) -> str: ...

    def no_results_answer(self, question: str, sql: str | None = None) -> str: ...
