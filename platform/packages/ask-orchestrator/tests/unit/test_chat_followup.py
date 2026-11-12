# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: the chat remembers the conversation, the same way in the
three modes.

The bug these pin
─────────────────
GONAC, 2026-11-11, Prod. After an answer of 29 rows the user asked why it was
29 rows and not 10 per channel, and was told "No puedo ver la consulta
anterior"; then asked to run it again with 10 customers per channel, and was
told "No puedo volver a ejecutar la consulta". The chat sent the history
without the SQL of each answer; Precise ignored it, Smart read it only to pick
the table, and ``routers/query.py`` never passed it to the SQL generator,
which accepts it.

The orchestrator now reads the history once: the last turns, each answer with
its SQL; a follow-up rewritten into a question that stands on its own before
any mode sees it; a question about an earlier answer answered from the turns,
without a query. The model is stubbed: these tests pin what reaches each step,
not how well the model rewrites.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ask_orchestrator import followup, organization_context, workspace_context, workspace_scope
from ask_orchestrator.models.requests import QueryRequest
from ask_orchestrator.routers import query as query_router

_USER = {"email": "tester@onibex.com", "bypass": True}

# Q12 of that chat (shortened), a statement of the shape that answered it, and
# the two follow-ups it could not answer, verbatim (Q13 and Q14).
_Q12 = (
    "De acuerdo a las ventas de los últimos 3 meses cerrados, que productos me han dejado de "
    "comprar mis clientes principales. Considera separar este top 10 por cada unos de los canales."
)
_Q12_SQL = (
    "SELECT canal, nombre_material, perdida FROM (SELECT canal, nombre_material, perdida, "
    "row_number() OVER (PARTITION BY canal ORDER BY perdida DESC) AS rn FROM (SELECT canal, "
    "nombre_material, sum(facturado) AS perdida FROM dbt_prd_bi.gold_mv_resumen "
    "GROUP BY canal, nombre_material)) WHERE rn <= 10"
)
_Q12_ANSWER = "Estos son los 10 productos con mayor pérdida de cada canal: 29 filas en total."
_Q13 = (
    "De la pregunta anterior por que me lo estas limitando a 29 registros en total y no a 10 "
    "registros por canal."
)
_Q14 = (
    "Si vuelve a ejecutar la consulta para que devuelva exactamente 10 clientes por canal, "
    "ordenados por facturado, y excluya a los clientes con valores en cero para que no ocupen "
    "lugares del top."
)
_Q14_COMPLETE = (
    "Según las ventas de agosto a octubre de 2026, ¿qué productos dejaron de comprar los 10 "
    "clientes principales de cada canal, ordenados por facturado y sin clientes en cero?"
)
_EXPLANATION = (
    "La consulta anterior tomó los 10 productos con más pérdida de cada canal, no clientes."
)


def _history() -> list[dict]:
    return [
        {"role": "user", "content": _Q12},
        {"role": "assistant", "content": _Q12_ANSWER, "sql": _Q12_SQL},
    ]


def _data(question: str) -> str:
    return json.dumps({"kind": "data", "question": question}, ensure_ascii=False)


_ABOUT_PREVIOUS = json.dumps({"kind": "previous_answer", "question": "otra cosa"})


class _Model:
    """Stands in for the chat model. Replies by the phase the call is tagged
    with, records every call, and charges it to the request's tracker as the
    real token callback does."""

    def __init__(self, rewrite: str | Exception = "", answer: str | Exception = ""):
        self.replies = {"followup_rewrite": rewrite, "followup_answer": answer}
        self.calls: list[tuple[str, str, str]] = []  # (phase, system, user)

    def invoke(self, messages):
        from ask_llm_gateway.infrastructure.token_tracker import _active_phase, get_active_tracker

        phase = _active_phase.get()
        self.calls.append((phase, messages[0].content, messages[-1].content))
        tracker = get_active_tracker()
        if tracker is not None:
            tracker.record(phase=phase, model="stub-model", input_tokens=100, output_tokens=10)
        reply = self.replies.get(phase, "")
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(content=reply)

    @property
    def phases(self) -> list[str]:
        return [phase for phase, _system, _user in self.calls]


@pytest.fixture
def model(monkeypatch):
    from ask_llm_gateway.application import factory

    def _install(**replies) -> _Model:
        stub = _Model(**replies)
        monkeypatch.setattr(factory, "build_llm", lambda _cfg: stub)
        monkeypatch.setattr(followup, "SettingsCache", SimpleNamespace(get=lambda: {}))
        return stub

    return _install


# ── recent_turns: what every step reads ──────────────────────────────────────


def test_each_answer_carries_the_sql_that_produced_it_and_questions_do_not():
    turns = followup.recent_turns(
        [
            {"role": "user", "content": _Q12, "sql": "SELECT 'not mine'"},
            {"role": "assistant", "content": _Q12_ANSWER, "sql": _Q12_SQL},
        ]
    )

    assert turns[0] == {"role": "user", "content": _Q12}
    assert turns[1]["role"] == "assistant"
    assert turns[1]["content"].startswith(_Q12_ANSWER)
    assert _Q12_SQL in turns[1]["content"]


def test_only_the_last_six_messages_are_read():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"mensaje {i}"}
        for i in range(10)
    ]

    turns = followup.recent_turns(history)

    assert followup.MAX_HISTORY_TURNS == 6
    assert [t["content"] for t in turns] == [f"mensaje {i}" for i in range(4, 10)]


def test_a_long_answer_keeps_its_start_and_its_sql_stays_whole():
    answer = "Resumen. " + "x" * (followup.MAX_TEXT_CHARS * 2)
    sql = "SELECT " + ", ".join(f"c{i}" for i in range(400)) + " FROM t"
    assert len(sql) < followup.MAX_SQL_CHARS

    (turn,) = followup.recent_turns([{"role": "assistant", "content": answer, "sql": sql}])

    assert turn["content"].startswith("Resumen. ")
    assert "x" * (followup.MAX_TEXT_CHARS + 1) not in turn["content"]
    assert sql in turn["content"]


def test_malformed_and_empty_turns_are_dropped():
    turns = followup.recent_turns(
        [
            None,
            "texto suelto",
            {"role": "user"},
            {"content": "sin rol"},
            {"role": "assistant", "content": "", "sql": "SELECT 1"},
        ]
    )

    assert len(turns) == 1
    assert turns[0]["role"] == "assistant" and "SELECT 1" in turns[0]["content"]


# ── resolve_followup: the one model call ─────────────────────────────────────


def test_a_follow_up_is_rewritten_from_the_turns_it_builds_on(model):
    llm = model(rewrite=_data(_Q14_COMPLETE))

    result = followup.resolve_followup(_Q14, followup.recent_turns(_history()))

    assert result == followup.FollowUp(_Q14_COMPLETE)
    ((phase, _system, user),) = llm.calls
    assert phase == "followup_rewrite"
    assert _Q12 in user and _Q12_SQL in user and _Q14 in user


def test_a_question_about_the_previous_answer_keeps_its_own_words(model):
    model(rewrite=_ABOUT_PREVIOUS)

    result = followup.resolve_followup(_Q13, followup.recent_turns(_history()))

    assert result == followup.FollowUp(_Q13, about_previous=True)


def test_a_fenced_reply_is_read(model):
    model(rewrite=f"```json\n{_data(_Q14_COMPLETE)}\n```")

    assert (
        followup.resolve_followup(_Q14, followup.recent_turns(_history())).question == _Q14_COMPLETE
    )


@pytest.mark.parametrize(
    "reply",
    ["Claro, esta es la pregunta completa.", '{"kind": "data"}', RuntimeError("model down")],
    ids=["prose", "no-question", "model-fails"],
)
def test_a_reply_that_cannot_be_used_leaves_the_question_as_it_came(model, reply):
    model(rewrite=reply)

    assert followup.resolve_followup(_Q14, followup.recent_turns(_history())) == followup.FollowUp(
        _Q14
    )


def test_without_turns_no_model_is_called(model):
    llm = model(rewrite=_data("nunca"))

    assert followup.resolve_followup(_Q12, []) == followup.FollowUp(_Q12)
    assert llm.calls == []


# ── run_query_pipeline: the same for the three modes ─────────────────────────


class _Scope:
    def get_entity_ids(self, _ws, env=None):
        return ["gold_mv_resumen"]

    def get_schema_entity_ids(self, _ws, env=None):
        return ["gold_mv_resumen"]


class _NoContext:
    def get_context_text(self, *_args):
        return None


class _Resolver:
    """The intent-resolution use case: records each request. Flash answers
    with its own SQL; Precise and Smart hand the schema on to the generator."""

    def __init__(self):
        self.requests: list = []

    def resolve(self, request):
        self.requests.append(request)
        trace = SimpleNamespace(tokens_used=0)
        if request.mode == "flash":
            return SimpleNamespace(
                sql="SELECT 1",
                rows=[{"n": 1}],
                answer="Flash.",
                disambiguation=None,
                error=None,
                trace=trace,
            )
        return SimpleNamespace(
            sql=None,
            rows=None,
            answer=None,
            disambiguation=None,
            error=None,
            yamls=[{"raw_yaml": "id: gold_mv_resumen"}],
            plan={},
            edges=[],
            trace=trace,
        )


@pytest.fixture
def pipeline(monkeypatch, model):
    """Runs ``run_query_pipeline`` with every step stubbed, and returns the
    response, what each step received, and the follow-up model."""
    from ask_llm_gateway.infrastructure import secrets as secrets_pkg

    def _run(question: str, history: list[dict] | None, *, mode: str = "precise", **replies):
        llm = model(**replies)
        seen = SimpleNamespace(classified=[], generations=[], formatted=[])
        resolver = _Resolver()
        seen.resolutions = resolver.requests

        def _classify(q):
            seen.classified.append(q)
            return "SQL_EXECUTION"

        def _generate(request):
            seen.generations.append(request)
            return SimpleNamespace(sql="SELECT 2", error=None, tokens_used=1)

        def _execute(request, question=""):
            seen.formatted.append(question)
            return SimpleNamespace(
                sql=request.sql, rows_dict=[{"n": 2}], answer="Respuesta.", error=None
            )

        monkeypatch.setattr(query_router._classifier, "classify", _classify)
        monkeypatch.setattr(workspace_scope, "_provider", _Scope())
        monkeypatch.setattr(organization_context, "_provider", _NoContext())
        monkeypatch.setattr(workspace_context, "_provider", _NoContext())
        monkeypatch.setattr(secrets_pkg, "is_db_configured", lambda _env=None: True)
        monkeypatch.setattr(
            secrets_pkg, "resolve_db_config", lambda env=None, **_kw: ("clickhouse", {"host": "db"})
        )
        monkeypatch.setattr(query_router, "get_default_use_case", lambda: resolver)
        monkeypatch.setattr(
            query_router, "_get_sql_generator", lambda _env: SimpleNamespace(generate=_generate)
        )
        monkeypatch.setattr(
            query_router, "_get_sql_executor", lambda: SimpleNamespace(execute_and_format=_execute)
        )

        req = QueryRequest(
            question=question,
            workspace_id="ws-1",
            mode=mode,
            env="prod",
            conversation_history=history,
        )
        return query_router.run_query_pipeline(req, _USER), seen, llm

    return _run


@pytest.mark.parametrize("mode", ["flash", "precise", "smart"])
def test_a_follow_up_reaches_every_mode_complete_and_with_the_earlier_sql(pipeline, mode):
    """«Vuelve a ejecutar la consulta con 10 clientes por canal»: the classifier,
    the mode and the SQL generator get the rewritten question; the mode and the
    generator get the turns with the SQL to change."""
    response, seen, llm = pipeline(_Q14, _history(), mode=mode, rewrite=_data(_Q14_COMPLETE))

    assert llm.phases == ["followup_rewrite"]
    assert seen.classified == [_Q14_COMPLETE]
    (resolution,) = seen.resolutions
    assert resolution.question == _Q14_COMPLETE
    # Flash's SQL prompt and Smart's selector render each turn as role: content.
    assert _Q12_SQL in resolution.conversation_history[-1]["content"]
    if mode == "flash":
        assert seen.generations == []  # Flash writes its own SQL from the same request
        return
    (generation,) = seen.generations
    assert generation.question == _Q14_COMPLETE
    assert _Q12 in generation.conversation_history
    assert _Q12_SQL in generation.conversation_history
    assert seen.formatted == [_Q14_COMPLETE]
    assert response.answer == "Respuesta."


def test_a_question_about_the_previous_answer_is_answered_without_a_query(pipeline):
    """«¿Por qué me lo limitas a 29 registros?»: answered from the answer and its
    SQL; nothing is classified, resolved, generated or run."""
    response, seen, llm = pipeline(_Q13, _history(), rewrite=_ABOUT_PREVIOUS, answer=_EXPLANATION)

    assert response.answer == _EXPLANATION
    assert response.sql is None and response.rows is None
    assert seen.classified == [] and seen.resolutions == [] and seen.generations == []
    assert llm.phases == ["followup_rewrite", "followup_answer"]
    _phase, _system, user = llm.calls[1]
    assert _Q12_SQL in user and _Q12_ANSWER in user and _Q13 in user
    assert set(response.tokens_breakdown.by_phase) == {"followup_rewrite", "followup_answer"}


def test_when_the_answer_step_fails_the_message_goes_on_as_a_question(pipeline):
    response, seen, _llm = pipeline(
        _Q13, _history(), rewrite=_ABOUT_PREVIOUS, answer=RuntimeError("model down")
    )

    assert seen.classified == [_Q13]
    assert len(seen.resolutions) == 1
    assert response.answer == "Respuesta."


def test_without_history_the_question_goes_on_untouched_and_no_model_is_called(pipeline):
    question = "¿Cuáles son mis clientes principales?"

    response, seen, llm = pipeline(question, None, rewrite=_data("nunca"))

    assert llm.calls == []
    assert seen.classified == [question]
    (generation,) = seen.generations
    assert generation.question == question
    assert generation.conversation_history == ""
    assert response.answer == "Respuesta."
