# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
The chat asks before answering when it has to, once, and answers with the reply.

Why
───
GONAC, 2026-11-12: «qué productos me han dejado de comprar mis clientes
principales» is "very ambiguous, it needs more detail": which comparison counts
as having stopped buying is theirs to say, and the semantic layer does not say
it. The agent guessed it four different ways on 2026-11-11. Now the SQL
generator may ask, in the call it already makes, and the reply is joined to the
question in code.

What must hold, or the chat stops answering again
─────────────────────────────────────────────────
- One clarification per question, enforced here and not in a prompt: the turn
  that replies to a clarification may not ask, even when the model tries.
- The reply is joined to the question explicitly. It never goes through the
  follow-up step, which could take it for a question about an earlier answer
  and answer without a query, nor through the classifier, so it never reaches a
  write to SAP.
- No state on the server: the clarification travels in the chat's history.
- What was settled is not lost to the six-message window.
- Only the chat asks: Teams, n8n, watsonx and the artifacts assume and say so.
- A switch turns asking off without a deploy.
- A message that asks for nothing (Q07, «Recuerda que estás utilizando la
  versión de clickhouse 22.1.3.7») gets a short reply, and no query.

The model is stubbed: these pin what reaches each step, not how well it asks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ask_orchestrator import (
    clarification,
    followup,
    organization_context,
    workspace_context,
    workspace_scope,
)
from ask_orchestrator.classification.macro_classifier import Classification
from ask_orchestrator.models.requests import QueryRequest
from ask_orchestrator.routers import query as query_router
from ask_sql_generation.domain.models import Clarification as Asked

_USER = {"email": "tester@onibex.com", "bypass": True}

# Q06 of GONAC's chat (shortened), the question the generator asks, and the
# reply the QA prepared from GONAC's answer (D3).
_Q06 = (
    "De acuerdo a las ventas de los últimos 3 meses cerrados, que productos me han dejado de "
    "comprar mis clientes principales. Considera separar este top por canal de distribución."
)
_ASKED = Asked(
    question="¿Qué cuenta como «dejó de comprar»?",
    options=[
        "Lo compró en agosto o septiembre y en octubre ya no",
        "Lo compraba de mayo a julio y de agosto a octubre ya no",
        "Lo compró menos que en los mismos meses del año anterior",
    ],
)
_REPLY = (
    "Que lo compró en agosto o en septiembre y en octubre ya no. El top 10 es de clientes "
    "por canal, ordenados por facturado y sin clientes en cero."
)
_A06 = "Estos son los productos que dejaron de comprar los 10 clientes principales de cada canal."
_A06_SQL = "SELECT canal, nombre_material FROM dbt_prd_bi.gold_mv_resumen"
_Q07 = "Recuerda que estas utilizando la versión de clickhouse 22.1.3.7"
_A07 = "Gracias. No guardo instrucciones entre preguntas: inclúyelo en la pregunta a la que aplica."
_ASSUMED = ["«Dejó de comprar» = lo compró en agosto o septiembre y en octubre ya no."]


def _clarification_turn(about: str = _Q06) -> dict:
    """The clarification as the chat sends it back: the response's object."""
    return {
        "role": "assistant",
        "content": clarification.render(_ASKED.question, _ASKED.options),
        "clarification": {"question": _ASKED.question, "options": _ASKED.options, "about": about},
    }


def _asked_then_replied() -> list[dict]:
    """Q06, the clarification, the reply and the answer, then Q07 and its reply:
    the six messages the chat sends with Q10."""
    return [
        {"role": "user", "content": _Q06},
        _clarification_turn(),
        {"role": "user", "content": _REPLY},
        {"role": "assistant", "content": _A06, "sql": _A06_SQL, "env": "prod"},
        {"role": "user", "content": _Q07},
        {"role": "assistant", "content": _A07},
    ]


class _Model:
    """The follow-up model: replies by phase and records each call."""

    def __init__(self, rewrite: str = "", unrelated: str = ""):
        self.replies = {"followup_rewrite": rewrite, "unrelated_answer": unrelated}
        self.calls: list[tuple[str, str]] = []

    def invoke(self, messages):
        from ask_llm_gateway.infrastructure.token_tracker import _active_phase

        phase = _active_phase.get()
        self.calls.append((phase, messages[-1].content))
        return SimpleNamespace(content=self.replies.get(phase, ""))

    @property
    def phases(self) -> list[str]:
        return [phase for phase, _ in self.calls]


class _Scope:
    def get_entity_ids(self, _ws, env=None):
        return ["gold_mv_resumen"]

    def get_schema_entity_ids(self, _ws, env=None):
        return ["gold_mv_resumen"]


class _NoContext:
    def get_context_text(self, *_args):
        return None


@pytest.fixture
def pipeline(monkeypatch):
    """Runs ``run_query_pipeline`` with every step stubbed. Returns the response
    (or the HTTPException), what each step received, and the follow-up model."""
    from ask_llm_gateway.application import factory
    from ask_llm_gateway.infrastructure import secrets as secrets_pkg

    def _run(
        question: str,
        history: list[dict] | None = None,
        *,
        can_clarify: bool = True,
        generated: list | None = None,
        classification: Classification | None = None,
        settings: dict | None = None,
        resolution_disambiguation=None,
        rewrite: str = "",
        unrelated: str = "",
    ):
        llm = _Model(rewrite=rewrite, unrelated=unrelated)
        monkeypatch.setattr(factory, "build_llm", lambda _cfg: llm)
        cfg = SimpleNamespace(get=lambda: settings or {})
        monkeypatch.setattr(followup, "SettingsCache", cfg)
        monkeypatch.setattr(clarification, "SettingsCache", cfg)

        seen = SimpleNamespace(
            classified=[], resolutions=[], generations=[], formatted=[], actions=[]
        )
        replies = list(generated or [SimpleNamespace(sql="SELECT 2")])

        def _classify(q):
            seen.classified.append(q)
            return classification or Classification("SQL_EXECUTION")

        def _resolve(request):
            seen.resolutions.append(request)
            return SimpleNamespace(
                sql=None,
                rows=None,
                answer="",
                error=None,
                disambiguation=resolution_disambiguation,
                yamls=[{"raw_yaml": "id: gold_mv_resumen"}],
                plan={},
                edges=[],
                trace=SimpleNamespace(tokens_used=0),
            )

        def _generate(request):
            seen.generations.append(request)
            reply = replies.pop(0)
            return SimpleNamespace(
                sql=getattr(reply, "sql", None),
                error=getattr(reply, "error", None),
                tokens_used=1,
                clarification=getattr(reply, "clarification", None),
                assumptions=getattr(reply, "assumptions", []),
            )

        def _execute(request, question="", assumptions=()):
            seen.formatted.append((question, list(assumptions)))
            return SimpleNamespace(
                sql=request.sql, rows_dict=[{"n": 2}], answer="Respuesta.", error=None
            )

        def _act(request):
            seen.actions.append(request.question)
            return SimpleNamespace(answer="Hecho.")

        monkeypatch.setattr(query_router._classifier, "classify", _classify)
        monkeypatch.setattr(workspace_scope, "_provider", _Scope())
        monkeypatch.setattr(organization_context, "_provider", _NoContext())
        monkeypatch.setattr(workspace_context, "_provider", _NoContext())
        monkeypatch.setattr(secrets_pkg, "is_db_configured", lambda _env=None: True)
        monkeypatch.setattr(
            secrets_pkg, "resolve_db_config", lambda env=None, **_kw: ("clickhouse", {"host": "db"})
        )
        monkeypatch.setattr(
            query_router, "get_default_use_case", lambda: SimpleNamespace(resolve=_resolve)
        )
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
            mode="precise",
            env="prod",
            session_id="s-1",
            conversation_history=history,
        )
        try:
            response = query_router.run_query_pipeline(req, _USER, can_clarify=can_clarify)
        except HTTPException as exc:
            response = exc
        return response, seen, llm

    return _run


def _asks() -> SimpleNamespace:
    return SimpleNamespace(clarification=_ASKED)


# ── Asking ───────────────────────────────────────────────────────────────────


def test_the_chat_asks_and_nothing_runs(pipeline):
    response, seen, _llm = pipeline(_Q06, generated=[_asks()])

    (generation,) = seen.generations
    assert generation.may_ask is True
    assert seen.formatted == []
    assert response.sql is None and response.rows is None
    assert response.clarification.question == _ASKED.question
    assert response.clarification.options == _ASKED.options
    assert response.clarification.about == _Q06
    assert response.answer.startswith(_ASKED.question)
    assert "- a) Lo compró en agosto o septiembre y en octubre ya no" in response.answer
    assert "- c) " in response.answer


def test_a_caller_with_no_one_to_answer_never_asks(pipeline):
    """Teams, n8n, watsonx and the artifacts call the pipeline without
    ``can_clarify``: the generator may not ask, and the answer states what it
    assumed."""
    answered = SimpleNamespace(sql="SELECT 2", assumptions=_ASSUMED)
    response, seen, _llm = pipeline(_Q06, can_clarify=False, generated=[answered])

    (generation,) = seen.generations
    assert generation.may_ask is False
    assert response.clarification is None
    assert seen.formatted == [(_Q06, _ASSUMED)]
    assert response.assumptions == _ASSUMED


def test_a_question_the_generator_asks_where_it_may_not_is_never_passed_on(pipeline):
    """The generator retries without asking; if a reply still carries a
    question, the orchestrator does not show it."""
    response, _seen, _llm = pipeline(_Q06, can_clarify=False, generated=[_asks()])

    assert response.clarification is None
    assert response.answer.startswith("Pipeline error")


def test_the_switch_turns_asking_off_without_a_deploy(pipeline):
    response, seen, _llm = pipeline(
        _Q06,
        settings={"chat": {"ask_for_clarification": False}},
        generated=[SimpleNamespace(sql="SELECT 2", assumptions=_ASSUMED)],
    )

    (generation,) = seen.generations
    assert generation.may_ask is False
    assert response.clarification is None
    assert response.assumptions == _ASSUMED


def test_the_switch_is_on_when_the_settings_do_not_name_it(monkeypatch):
    monkeypatch.setattr(clarification, "SettingsCache", SimpleNamespace(get=lambda: {}))
    assert clarification.asking_enabled() is True
    monkeypatch.setattr(clarification, "SettingsCache", SimpleNamespace(get=lambda: {"chat": {}}))
    assert clarification.asking_enabled() is True


# ── Replying ─────────────────────────────────────────────────────────────────


def test_the_reply_is_joined_to_the_question_and_answered(pipeline):
    history = [{"role": "user", "content": _Q06}, _clarification_turn()]
    response, seen, llm = pipeline(
        _REPLY, history, generated=[SimpleNamespace(sql="SELECT 2", assumptions=[])]
    )

    joined = clarification.join(
        clarification.Clarification(about=_Q06, question=_ASKED.question, options=_ASKED.options),
        _REPLY,
    )
    (resolution,) = seen.resolutions
    (generation,) = seen.generations
    assert resolution.question == joined
    assert generation.question == joined
    assert seen.formatted == [(joined, [])]
    # The question asked about, the options with their letters, and the reply.
    assert joined.startswith(_Q06)
    assert "a) Lo compró en agosto o septiembre y en octubre ya no" in joined
    assert joined.endswith(_REPLY)
    # Neither the clarification nor the question it asked about are left as
    # turns of the history: the joined question carries both.
    assert resolution.conversation_history == []
    assert response.answer == "Respuesta."


def test_the_turn_that_replies_never_asks_again(pipeline):
    """Even when the generator tries: the code allows no second question."""
    history = [{"role": "user", "content": _Q06}, _clarification_turn()]
    response, seen, _llm = pipeline(_REPLY, history, generated=[_asks()])

    (generation,) = seen.generations
    assert generation.may_ask is False
    assert response.clarification is None


def test_the_reply_skips_the_follow_up_step_and_the_classifier(pipeline):
    """A rewrite could take «la a» for a question about the previous answer and
    answer it with no query; the classifier could send it anywhere."""
    history = [{"role": "user", "content": _Q06}, _clarification_turn()]
    response, seen, llm = pipeline(
        "la a",
        history,
        classification=Classification("ACTION_EXECUTION"),
        rewrite=json.dumps({"kind": "previous_answer", "question": "la a"}),
    )

    assert llm.calls == []
    assert seen.classified == []
    assert seen.actions == []
    assert response.macro_intent == "SQL_EXECUTION"
    (generation,) = seen.generations
    assert generation.question.endswith("→ la a")


def test_the_reply_to_a_clarification_from_a_follow_up_completes_that_follow_up(pipeline):
    """``about`` is the question the generator saw, already completed."""
    completed = "Según agosto a octubre de 2026, ¿qué productos dejaron de comprar?"
    history = [{"role": "user", "content": "¿y por canal?"}, _clarification_turn(about=completed)]
    _response, seen, _llm = pipeline(_REPLY, history)

    (generation,) = seen.generations
    assert generation.question.startswith(completed)
    assert "¿y por canal?" not in generation.question


# ── The window ───────────────────────────────────────────────────────────────


def test_a_clarification_and_its_reply_take_one_place_of_the_window():
    """Q10 of chat A: the six messages the chat sends are four turns."""
    turns = followup.recent_turns(_asked_then_replied(), "prod")

    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[0]["content"].startswith(_Q06)
    assert turns[0]["content"].endswith(_REPLY)
    assert _A06_SQL in turns[1]["content"]


def test_what_was_settled_stays_in_view_as_long_as_its_question():
    """Two more questions and answers after Q06: six turns, the first still the
    clarified Q06."""
    history = _asked_then_replied() + [
        {"role": "user", "content": "¿Y por zona?"},
        {"role": "assistant", "content": "Por zona."},
    ]
    turns = followup.recent_turns(history, "prod")

    assert len(turns) == 6
    assert turns[0]["content"].endswith(_REPLY)


def test_the_follow_up_after_a_clarification_sees_it_settled(pipeline):
    """Q10: the rewrite gets the clarified Q06, so it can carry the comparison
    the user chose; the generator may ask, and has what it needs not to."""
    q10 = "que productos me han dejado de comprar mis clientes principales"
    completed = "¿Qué productos dejaron de comprar (agosto o septiembre y no en octubre)?"
    _response, seen, llm = pipeline(
        q10, _asked_then_replied(), rewrite=json.dumps({"kind": "data", "question": completed})
    )

    ((phase, user),) = llm.calls
    assert phase == "followup_rewrite"
    assert _REPLY in user and _ASKED.question in user
    (generation,) = seen.generations
    assert generation.question == completed
    assert _REPLY in generation.conversation_history
    assert generation.may_ask is True


def test_a_clarification_with_no_reply_yet_is_not_collapsed():
    history = [{"role": "user", "content": _Q06}, _clarification_turn()]

    assert clarification.collapse(history) == history


def test_split_pending_only_when_the_history_ends_with_a_clarification():
    earlier = [
        {"role": "user", "content": "Ventas de octubre"},
        {"role": "assistant", "content": "120."},
    ]
    turns, pending = clarification.split_pending(
        earlier + [{"role": "user", "content": _Q06}, _clarification_turn()]
    )
    assert turns == earlier
    assert pending.about == _Q06

    turns, pending = clarification.split_pending(_asked_then_replied())
    assert pending is None
    assert turns == _asked_then_replied()

    assert clarification.split_pending(None) == ([], None)


def test_a_malformed_clarification_is_an_ordinary_turn():
    turn = {"role": "assistant", "content": "x", "clarification": {"question": "¿?"}}

    assert clarification.clarification_of(turn) is None
    assert clarification.split_pending([turn]) == ([turn], None)


# ── Messages that ask for nothing, and unrelated ones ─────────────────────────


def test_a_message_that_asks_for_nothing_gets_its_reply_and_no_query(pipeline, caplog):
    caplog.set_level(logging.INFO, logger=query_router.logger.name)

    response, seen, _llm = pipeline(_Q07, classification=Classification("SQL_EXECUTION", _A07))

    assert response.answer == _A07
    assert seen.resolutions == [] and seen.generations == [] and seen.formatted == []
    assert response.sql is None and response.clarification is None
    (received,) = [r for r in caplog.records if r.getMessage() == "query received"]
    assert received.workspace_id == "ws-1"


def test_the_next_question_after_it_is_answered(pipeline):
    """The rest of Q07's case: the chat is not left broken."""
    history = [
        {"role": "user", "content": _Q07},
        {"role": "assistant", "content": _A07},
    ]
    response, seen, _llm = pipeline(
        _Q06, history, rewrite=json.dumps({"kind": "data", "question": _Q06})
    )

    assert response.answer == "Respuesta."
    assert len(seen.generations) == 1


def test_a_message_unrelated_to_the_layer_is_answered_by_the_model(pipeline):
    """Precise's dictionary L3: one model call writes the reply, in the user's
    language; no fixed text, no SQL."""
    from ask_intent_resolution.domain.result import Disambiguation

    response, seen, llm = pipeline(
        "¿Y lo otro?",
        resolution_disambiguation=Disambiguation(level="L3", message=""),
        unrelated="No pude relacionar tu mensaje con los datos disponibles.",
    )

    assert response.answer == "No pude relacionar tu mensaje con los datos disponibles."
    assert seen.generations == []
    assert llm.phases == ["unrelated_answer"]


def test_when_that_reply_fails_the_turn_reports_an_error(pipeline):
    from ask_intent_resolution.domain.result import Disambiguation

    outcome, _seen, _llm = pipeline(
        "¿Y lo otro?", resolution_disambiguation=Disambiguation(level="L3", message="")
    )

    assert isinstance(outcome, HTTPException)
    assert outcome.status_code == 500


# ── Callers ──────────────────────────────────────────────────────────────────


def test_only_the_chat_route_lets_the_pipeline_ask(monkeypatch):
    from ask_orchestrator.auth.validator import TokenClaims

    calls: list[dict] = []
    monkeypatch.setattr(
        query_router, "run_query_pipeline", lambda req, user, **kw: calls.append(kw)
    )
    claims = TokenClaims(sub="u", email="u@x", roles=[], issuer="keycloak")
    query_router.query(QueryRequest(question="q", workspace_id="ws-1"), claims)

    assert calls == [{"can_clarify": True}]


def test_external_ask_calls_the_pipeline_without_letting_it_ask(monkeypatch):
    from ask_orchestrator.external.models import ExternalAskRequest
    from ask_orchestrator.external.routers import ask as ask_router
    from ask_orchestrator.models.responses import QueryResponse

    calls: list[dict] = []

    def _pipeline(req, user, **kw):
        calls.append(kw)
        return QueryResponse(
            answer="a", macro_intent="SQL_EXECUTION", mode_used=req.mode, trace_id="t"
        )

    monkeypatch.setattr(ask_router, "run_query_pipeline", _pipeline)
    request = ExternalAskRequest(question="q", workspace_id="ws-1")
    asyncio.run(ask_router.ask(request, SimpleNamespace(email="e", sub="s", roles=[])))

    assert calls == [{}]


def test_an_artifact_states_what_its_data_request_assumed(monkeypatch):
    from ask_orchestrator.models.requests import ArtifactRequest
    from ask_orchestrator.routers import artifact as artifact_router

    prompts: list[str] = []

    class _LLM:
        def invoke(self, messages):
            prompts.append(messages[-1].content)
            return SimpleNamespace(content="# Doc")

    from ask_llm_gateway.application import factory

    monkeypatch.setattr(factory, "build_llm", lambda _cfg: _LLM())
    monkeypatch.setattr(artifact_router, "SettingsCache", SimpleNamespace(get=lambda: {}))
    req = ArtifactRequest(
        artifact_type="custom", purpose="p", data_focus="productos que dejaron de comprar"
    )

    artifact_router._generate_document(
        req,
        [{"name": "Main Dataset", "rows": [{"n": 1}]}],
        "SELECT 1",
        "t",
        assumptions=_ASSUMED,
    )

    assert _ASSUMED[0] in prompts[0]
