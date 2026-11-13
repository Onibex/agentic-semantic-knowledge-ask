# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Precise's Phase 1: one chat turn does not leak into the next, and each
dictionary level hands the orchestrator what it needs, with no text of its own.

The chat sends the same ``session_id`` on every turn of a conversation. When
the Phase 1 graph kept per-session state, the outcome of a non-data message
("remember you are on ClickHouse 22.1") survived into the next turn: the IR of
the following, valid question came out fine, yet the strategy still answered
"Phase 1 error: Could not interpret your question analytically" on every turn
after it, in English. A message the layer cannot place now ends the turn as L3
with no text (the orchestrator answers it in the user's language), and terms
that match several modules (L2) go on to the SQL generator with the other
readings, instead of a fixed English list that could come back on the very
question the user had just clarified.

These tests drive ``PreciseStrategy.resolve`` through the real bundle wiring
(``_get_bundle``) and the real Phase 1 graph. Only the services that would
reach an LLM or OpenSearch are replaced, so the graph's state handling is the
thing under test.
"""

from __future__ import annotations

from typing import Any

import pytest

from ask_intent_resolution.domain.ports import ResolutionRequest
from ask_intent_resolution.precise.domain.ir_models import SemanticPlanIR
from ask_intent_resolution.precise.strategy import PreciseStrategy
from ask_llm_gateway.application import factory as gateway_factory

SESSION = "chat-session-1"

NOT_A_DATA_QUESTION = "Recuerda que estás utilizando la versión de clickhouse 22.1.3.7"
NO_KNOWN_TERMS = "¿Y lo otro?"
SEVERAL_MODULES = "¿Cuánto llevamos?"
ONE_MODULE = "¿Cuánto facturamos?"
VALID_QUESTION = (
    "¿Qué productos me dejaron de comprar mis clientes principales en los "
    "últimos 3 meses cerrados, por canal de distribución?"
)

ENTITY = {"id": "gold_sales_summary", "raw_yaml": "id: gold_sales_summary\nlayer: gold\n"}

# What the IR generator returns for each message, as the LLM classified them.
_PLANS = {
    NOT_A_DATA_QUESTION: SemanticPlanIR(intent_summary="not analytical", is_impossible=True),
    # Not impossible, but no business terms: the graph falls back to the
    # semantic dictionary, finds nothing and answers with the L3 message.
    NO_KNOWN_TERMS: SemanticPlanIR(intent_summary="unclear follow-up"),
    SEVERAL_MODULES: SemanticPlanIR(intent_summary="how much so far"),
    ONE_MODULE: SemanticPlanIR(intent_summary="how much was billed"),
    VALID_QUESTION: SemanticPlanIR(
        intent_summary="products that top customers stopped buying, by channel",
        semantic_metrics=["net billed amount"],
        semantic_dimensions=["customer", "product", "distribution channel"],
    ),
}


class _FakeIRGenerator:
    def __init__(self, llm: Any) -> None:
        self.llm = llm

    def generate_plan(self, question: str) -> SemanticPlanIR:
        return _PLANS[question]


class _FakeEmbedder:
    def embed_query(self, _text: str) -> list[float]:
        return [0.0]


class _FakeOpenSearchRepository:
    def __init__(self, env: str | None = None) -> None:
        self.env = env
        self.client = object()


# What the semantic dictionary finds for each message with an empty IR.
_DICTIONARY = {
    SEVERAL_MODULES: [
        {"module": "SD", "canonical_label": "net billed amount", "type": "metric", "_score": 2.0},
        {
            "module": "MM",
            "canonical_label": "goods receipt quantity",
            "type": "metric",
            "_score": 1.8,
        },
    ],
    ONE_MODULE: [
        {"module": "SD", "canonical_label": "net billed amount", "type": "metric", "_score": 2.0},
    ],
}


class _FakeSemanticDictionary:
    def __init__(self, os_client: Any = None, embedder: Any = None) -> None:
        pass

    def search_hybrid(self, *, query: str, **_kwargs: Any) -> list[dict]:
        return _DICTIONARY.get(query, [])


class _FakeEntityResolver:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    def select_relevant_yamls(self, _plan_ir, top_k: int, allowed_ids=None) -> list[dict]:
        return [ENTITY]


class _FakePathSelector:
    def __init__(self, edge_repository: Any = None) -> None:
        pass

    def expand_context(self, anchors, max_hops, max_total_yamls, allowed_ids=None) -> list[dict]:
        return list(anchors)

    def get_edges_between(self, _entity_ids) -> list:
        return []


@pytest.fixture
def strategy(monkeypatch) -> PreciseStrategy:
    PreciseStrategy.reset()
    monkeypatch.setattr(gateway_factory, "llm_revision", lambda: "rev-test")
    monkeypatch.setattr(gateway_factory, "embedder_revision", lambda: "emb-test")
    monkeypatch.setattr(gateway_factory, "build_llm", lambda _cfg: object())
    monkeypatch.setattr(gateway_factory, "build_embedder", lambda _cfg: _FakeEmbedder())
    monkeypatch.setattr("ask_intent_resolution.precise.strategy._load_settings", lambda: {})
    monkeypatch.setattr(
        "ask_intent_resolution.precise.application.ir_generator.IRGeneratorService",
        _FakeIRGenerator,
    )
    monkeypatch.setattr(
        "ask_intent_resolution.precise.application.entity_resolution.EntityResolutionService",
        _FakeEntityResolver,
    )
    monkeypatch.setattr(
        "ask_intent_resolution.precise.application.path_selector.PathSelectorService",
        _FakePathSelector,
    )
    monkeypatch.setattr(
        "ask_knowledge_graph.application._legacy_dictionary.SemanticDictionaryService",
        _FakeSemanticDictionary,
    )
    monkeypatch.setattr(
        "ask_knowledge_graph.infrastructure.opensearch_repository.OpenSearchAskRepository",
        _FakeOpenSearchRepository,
    )
    yield PreciseStrategy()
    PreciseStrategy.reset()


def _ask(strategy: PreciseStrategy, question: str):
    return strategy.resolve(
        ResolutionRequest(question=question, mode="precise", session_id=SESSION, env="prod")
    )


def _assert_answered(result) -> None:
    assert result.error is None
    assert result.disambiguation is None
    assert "Phase 1 error" not in (result.answer or "")
    assert result.plan["semantic_metrics"] == ["net billed amount"]
    assert [e["id"] for e in result.yamls] == [ENTITY["id"]]


def _assert_unrelated(result) -> None:
    """L3: the turn stops, with no plan and no text for the user."""
    assert result.disambiguation is not None
    assert result.disambiguation.level == "L3"
    assert result.disambiguation.message == ""
    assert result.error is None
    assert result.answer == ""
    assert result.plan == {}
    assert result.yamls == []


def test_valid_question_after_a_non_data_message_is_answered(strategy):
    _assert_unrelated(_ask(strategy, NOT_A_DATA_QUESTION))

    _assert_answered(_ask(strategy, VALID_QUESTION))


def test_every_turn_after_a_non_data_message_is_answered(strategy):
    """The chat retried the same question twice more and failed each time."""
    _ask(strategy, NOT_A_DATA_QUESTION)

    for _ in range(3):
        _assert_answered(_ask(strategy, VALID_QUESTION))


def test_valid_question_after_a_message_with_no_known_terms_is_answered(strategy):
    _assert_unrelated(_ask(strategy, NO_KNOWN_TERMS))

    _assert_answered(_ask(strategy, VALID_QUESTION))


def test_non_data_message_after_a_valid_question_reports_its_own_error(strategy):
    """The reverse direction: the plan of an answered turn must not stand in
    for a later turn that has none."""
    _assert_answered(_ask(strategy, VALID_QUESTION))

    _assert_unrelated(_ask(strategy, NOT_A_DATA_QUESTION))


def test_terms_in_several_modules_go_on_with_the_top_one(strategy):
    """L2 no longer ends the turn: the plan follows the top module and the other
    readings travel on for the SQL generator to weigh."""
    result = _ask(strategy, SEVERAL_MODULES)

    assert result.error is None
    assert result.answer == ""
    assert result.plan["semantic_metrics"] == ["net billed amount"]
    assert result.plan["module_hint"] == "SD"
    assert [e["id"] for e in result.yamls] == [ENTITY["id"]]
    assert result.disambiguation is not None
    assert result.disambiguation.level == "L2"
    assert result.disambiguation.options == ["MM: goods receipt quantity"]


def test_terms_in_one_module_carry_no_other_readings(strategy):
    result = _ask(strategy, ONE_MODULE)

    assert result.disambiguation is None
    assert result.plan["semantic_metrics"] == ["net billed amount"]


def test_other_readings_do_not_reach_the_next_turn(strategy):
    _ask(strategy, SEVERAL_MODULES)

    _assert_answered(_ask(strategy, VALID_QUESTION))
