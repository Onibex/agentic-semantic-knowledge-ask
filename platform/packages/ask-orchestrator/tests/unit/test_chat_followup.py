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
without a query.

What the rewrite must not reach
───────────────────────────────
- A write to SAP: the action service gets the message as written, because it
  asks no confirmation and the rewrite carries values over from the history.
- Another environment's SQL: the picker is global to the chat, and dev's SQL
  names dev's schema (``dbt_qas_bi`` on GONAC). Only answers from the request's
  env, and that say so, lend their SQL.
- Past the workspace gate: an answer from the history still needs the
  workspace, and is logged like any question.
- A query, when the answer step fails: the reply says so instead.

The model is stubbed: these tests pin what reaches each step, not how well the
model rewrites.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

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
# The same question answered in dev, against QAS.
_DEV_SQL = "SELECT canal, sum(facturado) FROM dbt_qas_bi.gold_mv_resumen GROUP BY canal"


def _history(env: str | None = "prod") -> list[dict]:
    return [
        {"role": "user", "content": _Q12},
        {"role": "assistant", "content": _Q12_ANSWER, "sql": _Q12_SQL, "env": env},
    ]


def _data(question: str) -> str:
    return json.dumps({"kind": "data", "question": question}, ensure_ascii=False)


_ABOUT_PREVIOUS = json.dumps({"kind": "previous_answer", "question": "otra cosa"})


def _render(turns: list[dict[str, str]]) -> str:
    return followup.render_history(turns)


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
            {"role": "user", "content": _Q12, "sql": "SELECT 'not mine'", "env": "prod"},
            {"role": "assistant", "content": _Q12_ANSWER, "sql": _Q12_SQL, "env": "prod"},
        ],
        "prod",
    )

    assert turns[0] == {"role": "user", "content": _Q12}
    assert turns[1]["role"] == "assistant"
    assert turns[1]["content"].startswith(_Q12_ANSWER)
    assert _Q12_SQL in turns[1]["content"]


def test_sql_from_another_environment_or_from_none_is_left_out():
    """The picker is global to the chat: dev's SQL names dev's schema, and an
    answer saved before the env was recorded cannot say where it ran. Both keep
    their text."""
    history = [
        {"role": "assistant", "content": "En prod.", "sql": _Q12_SQL, "env": "prod"},
        {"role": "assistant", "content": "En dev.", "sql": _DEV_SQL, "env": "dev"},
        {"role": "assistant", "content": "Sin entorno.", "sql": "SELECT 'unknown'"},
    ]

    in_prod = followup.recent_turns(history, "prod")
    in_dev = followup.recent_turns(history, "dev")

    assert [t["content"].split("\n")[0] for t in in_prod] == ["En prod.", "En dev.", "Sin entorno."]
    assert _Q12_SQL in in_prod[0]["content"]
    assert in_prod[1]["content"] == "En dev." and in_prod[2]["content"] == "Sin entorno."
    assert _DEV_SQL in in_dev[1]["content"]
    assert _Q12_SQL not in _render(in_dev) and "unknown" not in _render(in_dev)
    assert "SELECT" not in _render(followup.recent_turns(history, None))


def test_only_the_last_six_messages_are_read():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"mensaje {i}"}
        for i in range(10)
    ]

    turns = followup.recent_turns(history, "prod")

    assert followup.MAX_HISTORY_TURNS == 6
    assert [t["content"] for t in turns] == [f"mensaje {i}" for i in range(4, 10)]


def test_a_long_answer_keeps_its_start_and_its_sql_stays_whole():
    answer = "Resumen. " + "x" * (followup.MAX_TEXT_CHARS * 2)
    sql = "SELECT " + ", ".join(f"c{i}" for i in range(400)) + " FROM t"
    assert len(sql) < followup.MAX_SQL_CHARS

    (turn,) = followup.recent_turns(
        [{"role": "assistant", "content": answer, "sql": sql, "env": "prod"}], "prod"
    )

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
            {"role": "assistant", "content": "", "sql": "SELECT 1", "env": "prod"},
        ],
        "prod",
    )

    assert len(turns) == 1
    assert turns[0]["role"] == "assistant" and "SELECT 1" in turns[0]["content"]


# ── resolve_followup: the one model call ─────────────────────────────────────


def test_a_follow_up_is_rewritten_from_the_turns_it_builds_on(model):
    llm = model(rewrite=_data(_Q14_COMPLETE))

    result = followup.resolve_followup(_Q14, followup.recent_turns(_history(), "prod"))

    assert result == followup.FollowUp(_Q14_COMPLETE)
    ((phase, _system, user),) = llm.calls
    assert phase == "followup_rewrite"
    assert _Q12 in user and _Q12_SQL in user and _Q14 in user


def test_a_question_about_the_previous_answer_keeps_its_own_words(model):
    model(rewrite=_ABOUT_PREVIOUS)

    result = followup.resolve_followup(_Q13, followup.recent_turns(_history(), "prod"))

    assert result == followup.FollowUp(_Q13, about_previous=True)


def test_a_fenced_reply_is_read(model):
    model(rewrite=f"```json\n{_data(_Q14_COMPLETE)}\n```")

    result = followup.resolve_followup(_Q14, followup.recent_turns(_history(), "prod"))

    assert result.question == _Q14_COMPLETE


@pytest.mark.parametrize(
    "reply",
    ["Claro, esta es la pregunta completa.", '{"kind": "data"}', RuntimeError("model down")],
    ids=["prose", "no-question", "model-fails"],
)
def test_a_reply_that_cannot_be_used_leaves_the_question_as_it_came(model, reply):
    model(rewrite=reply)

    result = followup.resolve_followup(_Q14, followup.recent_turns(_history(), "prod"))

    assert result == followup.FollowUp(_Q14)


def test_without_turns_no_model_is_called(model):
    llm = model(rewrite=_data("nunca"))

    assert followup.resolve_followup(_Q12, []) == followup.FollowUp(_Q12)
    assert llm.calls == []


# ── run_query_pipeline: the same for the three modes ─────────────────────────

_IN_SCOPE = ["gold_mv_resumen"]


class _Scope:
    """Workspace scope: ``None`` is a workspace that does not exist, ``[]`` one
    with nothing published to the env."""

    def __init__(self, ids: list[str] | None):
        self.ids = ids

    def get_entity_ids(self, _ws, env=None):
        return self.ids

    def get_schema_entity_ids(self, _ws, env=None):
        return self.ids


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
    response (or the HTTPException it raised), what each step received, and the
    follow-up model."""
    from ask_llm_gateway.infrastructure import secrets as secrets_pkg

    def _run(
        question: str,
        history: list[dict] | None,
        *,
        mode: str = "precise",
        intent: str = "SQL_EXECUTION",
        scope: list[str] | None = _IN_SCOPE,
        **replies,
    ):
        llm = model(**replies)
        seen = SimpleNamespace(classified=[], generations=[], formatted=[], actions=[])
        resolver = _Resolver()
        seen.resolutions = resolver.requests

        def _classify(q):
            seen.classified.append(q)
            return intent

        def _generate(request):
            seen.generations.append(request)
            return SimpleNamespace(sql="SELECT 2", error=None, tokens_used=1)

        def _execute(request, question=""):
            seen.formatted.append(question)
            return SimpleNamespace(
                sql=request.sql, rows_dict=[{"n": 2}], answer="Respuesta.", error=None
            )

        def _act(request):
            seen.actions.append(request.question)
            return SimpleNamespace(answer="Hecho.")

        monkeypatch.setattr(query_router._classifier, "classify", _classify)
        monkeypatch.setattr(workspace_scope, "_provider", _Scope(scope))
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
        monkeypatch.setattr(
            query_router, "_get_action_service", lambda: SimpleNamespace(execute=_act)
        )

        req = QueryRequest(
            question=question,
            workspace_id="ws-1",
            mode=mode,
            env="prod",
            conversation_history=history,
        )
        try:
            return query_router.run_query_pipeline(req, _USER), seen, llm
        except HTTPException as exc:
            return exc, seen, llm

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


def test_a_follow_up_in_prod_does_not_get_the_sql_of_an_answer_from_dev(pipeline):
    response, seen, llm = pipeline(_Q14, _history(env="dev"), rewrite=_data(_Q14_COMPLETE))

    (generation,) = seen.generations
    assert _Q12_ANSWER in generation.conversation_history
    assert _Q12_SQL not in generation.conversation_history
    (resolution,) = seen.resolutions
    assert _Q12_SQL not in _render(resolution.conversation_history)
    ((_phase, _system, user),) = llm.calls
    assert _Q12_SQL not in user


def test_an_action_gets_the_message_as_written_not_the_rewrite(pipeline):
    """«Cancélalo»: the classifier reads the rewrite, but the write to SAP gets
    what the user typed, without the order number the model carried over."""
    history = [
        {"role": "user", "content": "¿Cuál es el último pedido de TIENDAS TRES B?"},
        {
            "role": "assistant",
            "content": "Es el pedido 4500012345.",
            "sql": "SELECT 1",
            "env": "prod",
        },
    ]

    response, seen, _llm = pipeline(
        "Cancélalo",
        history,
        intent="ACTION_EXECUTION",
        rewrite=_data("Cancela el pedido de venta 4500012345 de TIENDAS TRES B."),
    )

    assert seen.classified == ["Cancela el pedido de venta 4500012345 de TIENDAS TRES B."]
    assert seen.actions == ["Cancélalo"]
    assert response.macro_intent == "ACTION_EXECUTION"


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


@pytest.mark.parametrize(
    ("scope", "status", "code"),
    [(None, 404, "WORKSPACE_NOT_FOUND"), ([], 400, "WORKSPACE_HAS_NO_ENTITIES")],
    ids=["no-such-workspace", "nothing-published"],
)
def test_an_answer_from_the_history_still_needs_the_workspace(pipeline, scope, status, code):
    outcome, _seen, llm = pipeline(
        _Q13, _history(), scope=scope, rewrite=_ABOUT_PREVIOUS, answer=_EXPLANATION
    )

    assert isinstance(outcome, HTTPException)
    assert outcome.status_code == status
    assert outcome.detail["error_code"] == code
    assert llm.phases == ["followup_rewrite"]  # refused before it is answered


def test_an_answer_from_the_history_is_logged_like_any_question(pipeline, caplog):
    caplog.set_level(logging.INFO, logger=query_router.logger.name)

    pipeline(_Q13, _history(), rewrite=_ABOUT_PREVIOUS, answer=_EXPLANATION)

    (received,) = [r for r in caplog.records if r.getMessage() == "query received"]
    assert received.user_email == _USER["email"]
    assert received.workspace_id == "ws-1"
    assert received.mode == "precise"
    assert received.macro_intent == "SQL_EXECUTION"


def test_when_the_answer_step_fails_it_says_so_and_runs_nothing(pipeline):
    """Running the message as a new question would answer something the user did
    not ask, and Precise would get it without the conversation."""
    response, seen, _llm = pipeline(
        _Q13, _history(), rewrite=_ABOUT_PREVIOUS, answer=RuntimeError("model down")
    )

    assert seen.classified == [] and seen.resolutions == []
    assert seen.generations == [] and seen.formatted == []
    assert response.sql is None and response.rows is None
    assert response.answer == followup.ANSWER_UNAVAILABLE


def test_without_history_the_question_goes_on_untouched_and_no_model_is_called(pipeline):
    question = "¿Cuáles son mis clientes principales?"

    response, seen, llm = pipeline(question, None, rewrite=_data("nunca"))

    assert llm.calls == []
    assert seen.classified == [question]
    (generation,) = seen.generations
    assert generation.question == question
    assert generation.conversation_history == ""
    assert response.answer == "Respuesta."
