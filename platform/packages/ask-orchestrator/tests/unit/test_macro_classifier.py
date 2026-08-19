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
"""

from __future__ import annotations

import pytest

from ask_orchestrator.classification.macro_classifier import (
    _LEGACY_TO_PUBLIC,
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
    assert classifier.classify("anything") == "SQL_EXECUTION"


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
    assert classifier.classify("anything") == expected_public
