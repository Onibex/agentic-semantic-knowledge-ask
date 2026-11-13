# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Unit tests for the orchestrator's MacroIntentClassifier.

Real LLM invocation is mocked — we only verify the contract:
  - 4 legacy intents map to the 3 public values (DASHBOARD_GEN folds into SQL_EXECUTION)
  - Empty input raises ValueError
  - LLM failures fail closed to SQL_EXECUTION (avoid breaking the chat path)
  - A message that asks for nothing gets its reply only when the classifier is
    sure: in doubt it is a data question
"""

from __future__ import annotations

import pytest

from ask_orchestrator.classification.macro_classifier import (
    _LEGACY_TO_PUBLIC,
    Classification,
    MacroIntentClassifier,
    _ClassifierOutput,
    _LegacyMacroIntent,
)


def test_legacy_to_public_maps_all_four_legacy_intents():
    assert _LEGACY_TO_PUBLIC[_LegacyMacroIntent.SCHEMA_QUERY] == "SCHEMA_QUERY"
    assert _LEGACY_TO_PUBLIC[_LegacyMacroIntent.DOCS_QUERY] == "DOCS_QUERY"
    assert _LEGACY_TO_PUBLIC[_LegacyMacroIntent.SQL_EXECUTION] == "SQL_EXECUTION"
    # Critical fold: DASHBOARD_GEN must collapse into SQL_EXECUTION.
    assert _LEGACY_TO_PUBLIC[_LegacyMacroIntent.DASHBOARD_GEN] == "SQL_EXECUTION"


def test_classify_empty_question_raises():
    classifier = MacroIntentClassifier()
    with pytest.raises(ValueError):
        classifier.classify("")
    with pytest.raises(ValueError):
        classifier.classify("   ")


def test_classify_llm_failure_falls_back_to_sql_execution(monkeypatch):
    """If the LLM raises, the classifier returns SQL_EXECUTION (fail-soft)."""
    classifier = MacroIntentClassifier()

    class _BoomChain:
        def invoke(self, _payload):
            raise RuntimeError("LLM down")

    class _StubParser:
        def get_format_instructions(self):
            return ""

    monkeypatch.setattr(
        MacroIntentClassifier,
        "_get_chain",
        classmethod(lambda cls: (_BoomChain(), _StubParser())),
    )
    assert classifier.classify("anything") == Classification("SQL_EXECUTION")


@pytest.mark.parametrize(
    "legacy_value,expected_public",
    [
        ("SCHEMA_QUERY", "SCHEMA_QUERY"),
        ("DOCS_QUERY", "DOCS_QUERY"),
        ("SQL_EXECUTION", "SQL_EXECUTION"),
        ("DASHBOARD_GEN", "SQL_EXECUTION"),  # FOLDED
    ],
)
def test_classify_returns_public_intent_with_stubbed_llm(
    monkeypatch, legacy_value, expected_public
):
    classifier = MacroIntentClassifier()

    class _Chain:
        def invoke(self, _payload):
            return _ClassifierOutput(
                intent=_LegacyMacroIntent(legacy_value),
                confidence="high",
                reasoning="stub",
            )

    class _StubParser:
        def get_format_instructions(self):
            return ""

    monkeypatch.setattr(
        MacroIntentClassifier,
        "_get_chain",
        classmethod(lambda cls: (_Chain(), _StubParser())),
    )
    assert classifier.classify("anything") == Classification(expected_public)


def _stub_output(monkeypatch, output: _ClassifierOutput) -> MacroIntentClassifier:
    class _Chain:
        def invoke(self, _payload):
            return output

    class _StubParser:
        def get_format_instructions(self):
            return ""

    monkeypatch.setattr(
        MacroIntentClassifier,
        "_get_chain",
        classmethod(lambda cls: (_Chain(), _StubParser())),
    )
    return MacroIntentClassifier()


_REPLY = "Gracias por el dato. No guardo instrucciones entre preguntas: inclúyelo en la pregunta."


def test_a_message_that_asks_for_nothing_gets_its_reply(monkeypatch):
    """Q07 of GONAC's chat: «Recuerda que estás utilizando la versión de
    clickhouse 22.1.3.7». No query; a short reply in the user's language."""
    classifier = _stub_output(
        monkeypatch,
        _ClassifierOutput(
            intent=_LegacyMacroIntent.CONVERSATION,
            confidence="high",
            reasoning="an instruction for later",
            reply=_REPLY,
        ),
    )

    assert classifier.classify("Recuerda que estás utilizando ClickHouse 22.1.3.7") == (
        Classification("SQL_EXECUTION", _REPLY)
    )


@pytest.mark.parametrize("confidence", ["medium", "low"])
def test_in_doubt_a_message_is_a_data_question(monkeypatch, confidence):
    classifier = _stub_output(
        monkeypatch,
        _ClassifierOutput(
            intent=_LegacyMacroIntent.CONVERSATION,
            confidence=confidence,
            reasoning="maybe",
            reply=_REPLY,
        ),
    )

    assert classifier.classify("¿y lo de ayer?") == Classification("SQL_EXECUTION")


def test_a_conversation_without_a_reply_is_a_data_question(monkeypatch):
    classifier = _stub_output(
        monkeypatch,
        _ClassifierOutput(
            intent=_LegacyMacroIntent.CONVERSATION, confidence="high", reasoning="x", reply="  "
        ),
    )

    assert classifier.classify("hola") == Classification("SQL_EXECUTION")


def test_a_reply_on_any_other_intent_is_ignored(monkeypatch):
    classifier = _stub_output(
        monkeypatch,
        _ClassifierOutput(
            intent=_LegacyMacroIntent.SQL_EXECUTION, confidence="high", reasoning="x", reply="hola"
        ),
    )

    assert classifier.classify("ventas de octubre") == Classification("SQL_EXECUTION")
