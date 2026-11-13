# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The generator asks the user only where asking is allowed, and once.

The chat lets the SQL generator answer with one question instead of SQL when
the question can be read in ways that return different data and neither the
question, the semantic layer nor the conversation settles which. In the same
call it sees all three. Everywhere else (Teams, n8n, watsonx, artifacts, the
turn that answers a clarification) it may not ask: it picks a reading and names
it in ``assumptions``. A reply that asks anyway, or asks without concrete
options, gets one more call that may not ask, so those turns always answer.
"""

from __future__ import annotations

import json

from ask_sql_generation.application.freeform_generator import FreeformSQLGeneratorService
from ask_sql_generation.application.sql_generator import FreeformSqlGenerator
from ask_sql_generation.domain.models import Clarification, SqlGenerationRequest

_YAML = (
    "id: gold_sales_summary\nlayer: gold\ndb_table_name: gold_mv_resumen\n"
    "fields:\n  - name: facturado\n    field_role: measure\n"
)
_QUESTION = "¿Qué productos me han dejado de comprar mis clientes principales?"
_ASK = {
    "clarification": {
        "question": "¿Qué cuenta como «dejó de comprar»?",
        "options": [
            "Lo compró en agosto o septiembre y en octubre ya no",
            "Lo compraba de mayo a julio y de agosto a octubre ya no",
        ],
    }
}
_SQL = {
    "sql": 'SELECT 1 FROM "gold_mv_resumen"',
    "table_name": "gold_mv_resumen",
    "explanation": "x",
    "assumptions": ["Dejó de comprar = lo compró en agosto o septiembre y en octubre ya no."],
}


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class _ScriptedLLM:
    """Replies with the scripted objects in order and records every prompt."""

    def __init__(self, *replies: dict) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    def invoke(self, messages):
        self.prompts.append(messages[0].content)
        return _Reply(json.dumps(self._replies.pop(0)))


def _generate(llm: _ScriptedLLM, *, may_ask: bool, readings=None) -> dict:
    return FreeformSQLGeneratorService(llm=llm, db_type="clickhouse").generate(
        question=_QUESTION,
        yamls=[_YAML],
        may_ask=may_ask,
        alternative_readings=readings,
        validate_scope=False,
    )


def test_a_prompt_that_may_ask_offers_the_question_and_its_rules():
    llm = _ScriptedLLM(_SQL)
    _generate(llm, may_ask=True)

    assert "CLARIFICATION ALLOWED" in llm.prompts[0]
    assert "OPTION C" in llm.prompts[0]


def test_a_prompt_that_may_not_ask_never_mentions_asking():
    llm = _ScriptedLLM(_SQL)
    _generate(llm, may_ask=False)

    assert "CLARIFICATION ALLOWED" not in llm.prompts[0]
    assert "OPTION C" not in llm.prompts[0]
    assert '"assumptions"' in llm.prompts[0]


def test_an_allowed_clarification_comes_back_without_sql():
    llm = _ScriptedLLM(_ASK)
    result = _generate(llm, may_ask=True)

    assert result["sql"] is None
    assert result["error"] is None
    assert result["clarification"] == _ASK["clarification"]
    assert len(llm.prompts) == 1


def test_a_clarification_where_asking_is_not_allowed_still_answers():
    """The turn that answers a clarification: the model asks again anyway."""
    llm = _ScriptedLLM(_ASK, _SQL)
    result = _generate(llm, may_ask=False)

    assert result["sql"] == _SQL["sql"]
    assert "clarification" not in result
    assert result["assumptions"] == _SQL["assumptions"]
    assert len(llm.prompts) == 2
    assert "ASKING THE USER IS NOT AVAILABLE" in llm.prompts[1]
    assert "OPTION C" not in llm.prompts[1]


def test_a_clarification_without_concrete_options_answers_instead():
    """An open question, with no readings to pick from, is not asked."""
    open_question = {"clarification": {"question": "¿Puedes dar más detalles?", "options": []}}
    llm = _ScriptedLLM(open_question, _SQL)
    result = _generate(llm, may_ask=True)

    assert result["sql"] == _SQL["sql"]
    assert "clarification" not in result
    assert len(llm.prompts) == 2


def test_a_second_attempt_to_ask_is_an_error_not_a_question():
    llm = _ScriptedLLM(_ASK, _ASK)
    result = _generate(llm, may_ask=False)

    assert result["sql"] is None
    assert "clarification" not in result
    assert result["error"]


def test_options_beyond_four_are_dropped():
    many = {"clarification": {"question": "¿Cuál?", "options": [f"opción {i}" for i in range(6)]}}
    result = _generate(_ScriptedLLM(many), may_ask=True)

    assert len(result["clarification"]["options"]) == 4


def test_assumptions_are_a_list_of_sentences():
    reply = dict(_SQL, assumptions="Periodo: 2026 a la fecha.")
    result = _generate(_ScriptedLLM(reply), may_ask=False)

    assert result["assumptions"] == ["Periodo: 2026 a la fecha."]


def test_other_readings_of_the_terms_reach_the_prompt():
    llm = _ScriptedLLM(_SQL)
    _generate(llm, may_ask=True, readings=["MM: purchase order quantity"])

    assert "OTHER READINGS OF THE QUESTION'S TERMS" in llm.prompts[0]
    assert "MM: purchase order quantity" in llm.prompts[0]


def test_the_typed_wrapper_carries_the_clarification_and_the_assumptions():
    asked = FreeformSqlGenerator(llm=_ScriptedLLM(_ASK), db_type="clickhouse").generate(
        SqlGenerationRequest(
            question=_QUESTION,
            yamls=[_YAML],
            db_type="clickhouse",
            may_ask=True,
            validate_scope=False,
        )
    )
    assert asked.sql is None
    assert asked.clarification == Clarification(
        question=_ASK["clarification"]["question"], options=_ASK["clarification"]["options"]
    )

    answered = FreeformSqlGenerator(llm=_ScriptedLLM(_SQL), db_type="clickhouse").generate(
        SqlGenerationRequest(
            question=_QUESTION, yamls=[_YAML], db_type="clickhouse", validate_scope=False
        )
    )
    assert answered.clarification is None
    assert answered.assumptions == _SQL["assumptions"]
