# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for the SqlExecutorService — adapters and formatter are stubbed."""

from __future__ import annotations

import pytest

from ask_sql_executor.application.executor_service import SqlExecutorService
from ask_sql_executor.application.result_formatter import LLMResultFormatter
from ask_sql_executor.domain.errors import UnsupportedDbTypeError
from ask_sql_executor.domain.models import (
    ExecutionRequest,
    ExecutionResult,
    FormattedResult,
)


class _FakeFormatter:
    def __init__(self):
        self.format_calls: list[tuple] = []
        self.no_results_calls: list[tuple] = []

    def format_rows(self, columns, rows, question):
        self.format_calls.append((columns, rows, question))
        return f"{len(rows)} rows formatted"

    def no_results_answer(self, question, sql=None):
        self.no_results_calls.append((question, sql))
        return "No data found."


def test_unsupported_db_type_raises(monkeypatch):
    svc = SqlExecutorService(_FakeFormatter())
    with pytest.raises(UnsupportedDbTypeError):
        svc.execute(ExecutionRequest(sql="SELECT 1", db_type="oracle", db_config={}))  # type: ignore[arg-type]


def test_execute_hana_dispatches_to_hana_adapter(monkeypatch):
    captured = {}

    def fake_hana(req):
        captured["req"] = req
        return ExecutionResult(success=True, columns=["c"], rows=[(1,)], row_count=1)

    monkeypatch.setattr(
        "ask_sql_executor.application.executor_service.get_adapter",
        lambda db_type: fake_hana,
    )
    svc = SqlExecutorService(_FakeFormatter())
    result = svc.execute(ExecutionRequest(sql="SELECT 1", db_type="hana", db_config={}))
    assert result.success is True
    assert captured["req"].db_type == "hana"


def test_execute_postgresql_dispatches_to_pg_adapter(monkeypatch):
    captured = {}

    def fake_pg(req):
        captured["req"] = req
        return ExecutionResult(success=True, columns=["c"], rows=[(1,)], row_count=1)

    monkeypatch.setattr(
        "ask_sql_executor.application.executor_service.get_adapter",
        lambda db_type: fake_pg,
    )
    svc = SqlExecutorService(_FakeFormatter())
    result = svc.execute(
        ExecutionRequest(sql="SELECT 1", db_type="postgresql", db_config={"host": "h"})
    )
    assert result.success is True
    assert captured["req"].db_type == "postgresql"


def test_execute_and_format_with_rows(monkeypatch):
    monkeypatch.setattr(
        "ask_sql_executor.application.executor_service.get_adapter",
        lambda db_type: (
            lambda req: ExecutionResult(
                success=True,
                columns=["plant", "qty"],
                rows=[("1000", 42), ("2000", 17)],
                row_count=2,
            )
        ),
    )
    formatter = _FakeFormatter()
    svc = SqlExecutorService(formatter)
    formatted = svc.execute_and_format(
        ExecutionRequest(sql="SELECT 1", db_type="hana", db_config={}),
        question="how many?",
    )
    assert isinstance(formatted, FormattedResult)
    assert formatted.error is None
    assert formatted.row_count == 2
    assert formatted.rows_dict == [{"plant": "1000", "qty": 42}, {"plant": "2000", "qty": 17}]
    assert formatted.answer == "2 rows formatted"
    assert len(formatter.format_calls) == 1
    assert len(formatter.no_results_calls) == 0


def test_execute_and_format_no_rows_calls_no_results_helper(monkeypatch):
    monkeypatch.setattr(
        "ask_sql_executor.application.executor_service.get_adapter",
        lambda db_type: (
            lambda req: ExecutionResult(success=True, columns=["c"], rows=[], row_count=0)
        ),
    )
    formatter = _FakeFormatter()
    svc = SqlExecutorService(formatter)
    formatted = svc.execute_and_format(
        ExecutionRequest(sql="SELECT 1 WHERE FALSE", db_type="hana", db_config={}),
        question="anything?",
    )
    assert formatted.row_count == 0
    assert formatted.rows_dict == []
    assert formatted.answer == "No data found."
    assert formatter.no_results_calls == [("anything?", "SELECT 1 WHERE FALSE")]


def test_execute_and_format_propagates_execution_error(monkeypatch):
    monkeypatch.setattr(
        "ask_sql_executor.application.executor_service.get_adapter",
        lambda db_type: lambda req: ExecutionResult(success=False, error="HANA boom"),
    )
    svc = SqlExecutorService(_FakeFormatter())
    formatted = svc.execute_and_format(
        ExecutionRequest(sql="SELECT 1", db_type="hana", db_config={}),
        question="x",
    )
    assert formatted.error == "HANA boom"
    assert "Pipeline error" in formatted.answer
    assert formatted.row_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# LLMResultFormatter (LLM is stubbed so we do not pay tokens)
# ─────────────────────────────────────────────────────────────────────────────
def test_llm_formatter_returns_no_results_message_when_rows_empty():
    formatter = LLMResultFormatter(llm=object())  # llm not invoked in this branch
    answer = formatter.format_rows(["c"], [], "x")
    assert answer == "No results found for your query."


def test_llm_formatter_invokes_llm_for_format_rows():
    class _LLM:
        def __init__(self):
            self.calls = []

        def invoke(self, prompt):
            self.calls.append(prompt)

            class _R:
                content = "summary"

            return _R()

    llm = _LLM()
    formatter = LLMResultFormatter(llm=llm)
    answer = formatter.format_rows(["plant", "qty"], [("1000", 42)], "how many?")
    assert answer == "summary"
    assert "USER QUESTION: how many?" in llm.calls[0]
    assert "plant: 1000" in llm.calls[0]


def test_llm_formatter_falls_back_when_llm_raises():
    class _BoomLLM:
        def invoke(self, prompt):
            raise RuntimeError("LLM down")

    formatter = LLMResultFormatter(llm=_BoomLLM())
    answer = formatter.format_rows(["c"], [(1,)], "x")
    assert "Found 1 result" in answer


def test_llm_formatter_no_results_uses_llm():
    class _LLM:
        def invoke(self, prompt):
            assert "0 rows" in prompt
            assert "SELECT 1" in prompt

            class _R:
                content = "no luck"

            return _R()

    formatter = LLMResultFormatter(llm=_LLM())
    answer = formatter.no_results_answer("x", sql="SELECT 1")
    assert answer == "no luck"
