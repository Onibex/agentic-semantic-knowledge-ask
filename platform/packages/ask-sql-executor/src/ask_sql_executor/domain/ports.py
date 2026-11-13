# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

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

from collections.abc import Sequence
from typing import Any, Protocol

from .models import ExecutionRequest, ExecutionResult, FormattedResult


class SqlExecutor(Protocol):
    """Inbound — orchestrator-facing."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run the SQL and return rows as tuples (driver-native shape)."""
        ...

    def execute_and_format(
        self,
        request: ExecutionRequest,
        *,
        question: str,
        assumptions: Sequence[str] = (),
    ) -> FormattedResult:
        """Run + format. Used by the orchestrator's SQL_EXECUTION branch.
        ``assumptions`` are the readings the SQL took for what the question left
        open; the answer states them."""
        ...


class ResultFormatter(Protocol):
    """Outbound — pluggable so the orchestrator can swap LLMs / template engines."""

    def format_rows(
        self,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        question: str,
        sql: str | None = None,
        assumptions: Sequence[str] = (),
    ) -> str:
        """``sql`` is the statement that produced the rows: what the answer reads
        the period from. ``assumptions``: what the answer must say it assumed."""
        ...

    def no_results_answer(
        self, question: str, sql: str | None = None, assumptions: Sequence[str] = ()
    ) -> str: ...
