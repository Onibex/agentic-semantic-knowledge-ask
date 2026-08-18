# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""domain.language + infrastructure.language_config — the authoring-language flag.

The resolver's precedence is what a misconfigured deployment lives or dies by
(the failure mode is degraded retrieval, never an error), so it is pinned value
by value. The directives are asserted BRACE-FREE because two consumers feed them
through a ``ChatPromptTemplate``, where a stray brace becomes a template
variable and breaks prompt construction at import time.
"""

from __future__ import annotations

import pytest

from ask_knowledge_graph.domain.language import (
    SemanticLanguage,
    authoring_directive,
    extraction_directive,
)
from ask_knowledge_graph.infrastructure.language_config import resolve_semantic_language

# ── vocabulary ───────────────────────────────────────────────────────────────


def test_values_and_labels():
    assert SemanticLanguage.EN.value == "en"
    assert SemanticLanguage.ES.value == "es"
    assert SemanticLanguage.EN.label == "English"
    assert SemanticLanguage.ES.label == "Spanish"
    # str-enum so it interpolates as its value in prompts/logs
    assert f"{SemanticLanguage.ES}" == "SemanticLanguage.ES" or SemanticLanguage.ES == "es"


def test_closed_set_is_exactly_en_es():
    assert {m.value for m in SemanticLanguage} == {"en", "es"}


# ── directives ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", list(SemanticLanguage))
def test_directives_are_brace_free(lang):
    for text in (authoring_directive(lang), extraction_directive(lang)):
        assert "{" not in text and "}" not in text


def test_authoring_directive_names_the_language_and_protects_the_enums():
    text = authoring_directive(SemanticLanguage.ES)
    assert "SPANISH" in text
    assert "description" in text and "synonyms" in text
    # The closed vocabularies must stay English even in an ES deployment.
    assert "ORDER TO CASH" in text
    assert "field_role" in text
    # Identifiers are never prose.
    assert "physical column names" in text
    # Bronze alias exception (BRONZE_LAYER.md §2).
    assert "Bronze" in text
    # The interim accent rule for synonyms (no asciifolding yet — W3).
    assert "WITHOUT accents" in text


def test_extraction_directive_states_the_retrieval_reason():
    text = extraction_directive(SemanticLanguage.ES)
    assert "SPANISH" in text
    assert "retrieval query" in text
    text_en = extraction_directive(SemanticLanguage.EN)
    assert "ENGLISH" in text_en


# ── resolver precedence ──────────────────────────────────────────────────────


def test_default_is_english(monkeypatch):
    monkeypatch.delenv("ASK_SEMANTIC_LANGUAGE", raising=False)
    assert resolve_semantic_language({}) is SemanticLanguage.EN


def test_settings_key_is_read(monkeypatch):
    monkeypatch.delenv("ASK_SEMANTIC_LANGUAGE", raising=False)
    assert resolve_semantic_language({"semantic_layer": {"language": "es"}}) is SemanticLanguage.ES


def test_env_beats_settings(monkeypatch):
    monkeypatch.setenv("ASK_SEMANTIC_LANGUAGE", "en")
    cfg = {"semantic_layer": {"language": "es"}}
    assert resolve_semantic_language(cfg) is SemanticLanguage.EN


def test_env_value_is_case_insensitive_and_trimmed(monkeypatch):
    monkeypatch.setenv("ASK_SEMANTIC_LANGUAGE", "  ES ")
    assert resolve_semantic_language({}) is SemanticLanguage.ES


def test_empty_settings_section_falls_back(monkeypatch):
    monkeypatch.delenv("ASK_SEMANTIC_LANGUAGE", raising=False)
    assert resolve_semantic_language({"semantic_layer": {}}) is SemanticLanguage.EN
    assert resolve_semantic_language({"semantic_layer": None}) is SemanticLanguage.EN


def test_invalid_value_raises_instead_of_defaulting(monkeypatch):
    monkeypatch.setenv("ASK_SEMANTIC_LANGUAGE", "spanish")
    with pytest.raises(ValueError, match="spanish"):
        resolve_semantic_language({})
    monkeypatch.delenv("ASK_SEMANTIC_LANGUAGE")
    with pytest.raises(ValueError, match="pt"):
        resolve_semantic_language({"semantic_layer": {"language": "pt"}})
