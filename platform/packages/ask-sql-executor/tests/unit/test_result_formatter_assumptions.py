# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The answer says what the query assumed.

When a question leaves open something that changes the result and the agent
may not ask (Teams, n8n, watsonx, artifacts, the turn that answers a
clarification), the SQL generator picks a reading and names it in
``assumptions``. The reader has to see which reading the figures follow, so the
formatter is told to say it, with rows and without them.
"""

from __future__ import annotations

from ask_sql_executor.application.executor_service import SqlExecutorService
from ask_sql_executor.application.result_formatter import LLMResultFormatter
from ask_sql_executor.domain.models import ExecutionRequest, ExecutionResult

_ASSUMED = "Dejó de comprar = lo compró en agosto o septiembre y en octubre ya no."


class _CapturingLLM:
    def __init__(self):
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)

        class _R:
            content = "respuesta"

        return _R()


def _run(monkeypatch, rows, assumptions):
    monkeypatch.setattr(
        "ask_sql_executor.application.executor_service.get_adapter",
        lambda db_type: (
            lambda req: ExecutionResult(
                success=True, columns=["producto"], rows=rows, row_count=len(rows)
            )
        ),
    )
    llm = _CapturingLLM()
    SqlExecutorService(LLMResultFormatter(llm=llm)).execute_and_format(
        ExecutionRequest(sql="SELECT 1", db_type="clickhouse", db_config={}),
        question="¿Qué productos me dejaron de comprar?",
        assumptions=assumptions,
    )
    return llm.prompts[0]


def test_an_answer_with_rows_states_what_the_query_assumed(monkeypatch):
    prompt = _run(monkeypatch, [("PAPAS",)], [_ASSUMED])

    assert "ASSUMED" in prompt
    assert _ASSUMED in prompt


def test_an_answer_without_rows_states_it_too(monkeypatch):
    prompt = _run(monkeypatch, [], [_ASSUMED])

    assert _ASSUMED in prompt


def test_nothing_assumed_adds_nothing(monkeypatch):
    prompt = _run(monkeypatch, [("PAPAS",)], ["", "   "])

    assert "ASSUMED" not in prompt
