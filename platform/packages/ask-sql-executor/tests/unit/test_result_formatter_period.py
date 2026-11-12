# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: the answer can say which period it covers, and whether it has closed.

The bug these pin
─────────────────
The formatter got the question and the rows, not the SQL, so it could not know
which period the rows cover. In GONAC's chat of 2026-11-11, Q24 answered "no
zone reached its target" for November on day 9 of 21 of the month, which reads
as a bad month; Q01 to Q03 never said they covered 2026 to date or all history.
The formatter now gets the statement that produced the rows, and today's date.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import ask_sql_executor.application.result_formatter as formatter_mod
from ask_sql_executor.application.executor_service import SqlExecutorService
from ask_sql_executor.application.result_formatter import LLMResultFormatter
from ask_sql_executor.domain.models import ExecutionRequest, ExecutionResult

# Q24: compliance with the month's target, by zone, on 2026-11-12.
_Q24_SQL = (
    'SELECT "zona", round(toFloat64(sum("facturado")), 2) AS facturado_total, '
    'round(toFloat64(sum("objetivo")), 2) AS objetivo_total, '
    'round(100 * toFloat64(sum("facturado")) / nullIf(toFloat64(sum("objetivo")), 0), 2) AS cumplimiento_pct '
    'FROM "dbt_prd_bi"."gold_mv_resumen" '
    'WHERE "ejercicio" = toYear(today()) AND "periodo" = toMonth(today()) GROUP BY "zona"'
)
_Q24_COLUMNS = ["zona", "facturado_total", "objetivo_total", "cumplimiento_pct"]
_Q24_ROWS = [
    ("DH", 23803161.04, 64408905.51, 36.96),
    ("Sur", 49967100.58, 155370288.99, 32.16),
    ("Norte", 21128128.37, 51434536.19, 41.08),
]


class _CapturingLLM:
    def __init__(self):
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)

        class _R:
            content = "respuesta"

        return _R()


@pytest.fixture
def on_2026_11_12(monkeypatch):
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 12, 17, 32, tzinfo=tz or UTC)

    monkeypatch.setattr(formatter_mod, "datetime", _Frozen)


def test_q24_the_model_gets_the_sql_and_today_to_tell_a_month_in_progress(on_2026_11_12):
    llm = _CapturingLLM()

    LLMResultFormatter(llm=llm).format_rows(
        _Q24_COLUMNS, _Q24_ROWS, "¿Cuál es el cumplimiento del objetivo por zona?", sql=_Q24_SQL
    )

    prompt = llm.prompts[0]
    words = " ".join(prompt.split())  # the instructions wrap; compare them as prose
    assert _Q24_SQL in prompt
    assert "TODAY: 2026-11-12 (UTC)" in prompt
    assert "say which period the figures cover" in words
    assert "If the period reaches the current month, say it has not closed yet" in words
    assert "a figure below its target is not a final result" in words
    assert "do not quote it" in words


def test_a_query_with_no_date_filter_is_said_to_cover_all_the_data(on_2026_11_12):
    """Q02 and Q03 ranked customers over all history and never said so."""
    llm = _CapturingLLM()
    sql = 'SELECT "canal_distribucion", sum("facturado") AS facturado_total FROM "gold_mv_resumen" GROUP BY 1'

    LLMResultFormatter(llm=llm).format_rows(["canal_distribucion", "facturado_total"], [("01", 1.0)], "q", sql=sql)

    assert "If the SQL filters no dates, say they cover all the data available." in " ".join(llm.prompts[0].split())


def test_today_is_computed_per_call_not_frozen_at_import(monkeypatch):
    """The orchestrator process outlives a day; a month closes while it runs."""
    llm = _CapturingLLM()

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 12, 1, 0, 5, tzinfo=tz or UTC)

    monkeypatch.setattr(formatter_mod, "datetime", _Later)
    LLMResultFormatter(llm=llm).format_rows(_Q24_COLUMNS, _Q24_ROWS, "q", sql=_Q24_SQL)

    assert "TODAY: 2026-12-01 (UTC)" in llm.prompts[0]


def test_without_the_sql_there_is_no_period_block():
    llm = _CapturingLLM()

    LLMResultFormatter(llm=llm).format_rows(_Q24_COLUMNS, _Q24_ROWS, "q")

    assert "SQL THAT PRODUCED THE ROWS" not in llm.prompts[0]
    assert "TODAY:" not in llm.prompts[0]


def test_the_service_hands_the_formatter_the_statement_that_ran(monkeypatch):
    """The ClickHouse adapter may rewrite the statement (FINAL); the period is
    read from what produced the rows."""
    monkeypatch.setattr(
        "ask_sql_executor.application.executor_service.get_adapter",
        lambda db_type: (
            lambda req: ExecutionResult(
                success=True,
                columns=_Q24_COLUMNS,
                rows=_Q24_ROWS,
                row_count=len(_Q24_ROWS),
                executed_sql=_Q24_SQL.replace('"gold_mv_resumen"', '"gold_mv_resumen" FINAL'),
            )
        ),
    )
    llm = _CapturingLLM()

    SqlExecutorService(LLMResultFormatter(llm=llm)).execute_and_format(
        ExecutionRequest(sql=_Q24_SQL, db_type="clickhouse", db_config={}), question="q"
    )

    assert '"gold_mv_resumen" FINAL' in llm.prompts[0]
