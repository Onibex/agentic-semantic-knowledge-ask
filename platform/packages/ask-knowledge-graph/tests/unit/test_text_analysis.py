# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The searched-text analyzer (PLAN_SEMANTIC_LANGUAGE.md W3).

These pin the SHAPE of the analysis block and the mappings that use it. The
behavioural gate — `_analyze` returning the SAME token for `crédito` and
`credito` — needs a live cluster and lives in the e2e checklist; what can break
silently here is the filter ORDER and a field quietly staying `keyword`.
"""

from __future__ import annotations

import pytest

from ask_knowledge_graph.infrastructure.opensearch_repository import (
    _ASK_TEXT_ANALYZER,
    _text_analysis_settings,
)


def _chain(language: str) -> list[str]:
    return _text_analysis_settings(language)["analyzer"][_ASK_TEXT_ANALYZER]["filter"]


@pytest.mark.parametrize("language", ["en", "es"])
def test_folding_runs_before_stemming(language):
    """`asciifolding` must feed the stemmer, not follow it — otherwise the
    accented and unaccented forms reduce to two different stems and BM25 still
    misses."""
    chain = _chain(language)
    assert "asciifolding" in chain
    assert chain.index("asciifolding") < chain.index("ask_stemmer")
    # lowercase first, so folding and stopwords see one case
    assert chain.index("lowercase") < chain.index("asciifolding")


@pytest.mark.parametrize("language", ["en", "es"])
def test_original_accented_term_is_not_preserved(language):
    """`preserve_original` would re-index the accented variant and defeat the
    fold, so the filter must stay the plain built-in name."""
    assert "asciifolding" in _chain(language)
    assert "ask_fold" not in _text_analysis_settings(language)["filter"]


def test_language_selects_stopwords_and_stemmer():
    es = _text_analysis_settings("es")["filter"]
    assert es["ask_stop"]["stopwords"] == "_spanish_"
    assert es["ask_stemmer"]["language"] == "light_spanish"
    en = _text_analysis_settings("en")["filter"]
    assert en["ask_stop"]["stopwords"] == "_english_"
    assert en["ask_stemmer"]["language"] == "english"


def test_unknown_language_falls_back_to_english_instead_of_breaking_the_index():
    # The resolver rejects unknown values, so this is belt-and-braces: an index
    # must never fail to CREATE because of a language token.
    assert _text_analysis_settings("pt")["filter"]["ask_stop"]["stopwords"] == "_english_"
    assert _text_analysis_settings("")["filter"]["ask_stemmer"]["language"] == "english"


def test_analysis_block_is_attached_to_every_registry_index(monkeypatch):
    """The three registry indices + the RAG index must all carry the analyzer;
    a mapping that silently keeps `standard` is the defect this prevents."""
    monkeypatch.setenv("ASK_SEMANTIC_LANGUAGE", "es")

    captured: dict[str, dict] = {}

    class _Indices:
        def exists(self, index):
            return False

        def create(self, index, body):
            captured[index] = body

    class _Client:
        def __init__(self):
            self.indices = _Indices()

    from ask_knowledge_graph.infrastructure import opensearch_repository as mod

    monkeypatch.setattr(mod, "OpenSearch", lambda **kwargs: _Client())
    repo = mod.OpenSearchAskRepository()
    repo._ensure_indices_exist()

    assert captured, "no index was created"
    for index, body in captured.items():
        analysis = body["settings"]["analysis"]
        assert analysis["analyzer"][_ASK_TEXT_ANALYZER]["filter"][1] == "asciifolding", index
        assert analysis["filter"]["ask_stop"]["stopwords"] == "_spanish_", index

    entity = next(b for i, b in captured.items() if "entity" in i)
    props = entity["mappings"]["properties"]
    # The two mapping bugs fixed with the analyzer.
    assert props["name"]["type"] == "text"  # was keyword → highest boost was inert
    assert props["name"]["fields"]["keyword"]["type"] == "keyword"
    assert props["business_terms"]["analyzer"] == _ASK_TEXT_ANALYZER  # was undeclared

    fields = next(b for i, b in captured.items() if "field" in i)
    fprops = fields["mappings"]["properties"]
    assert fprops["name"]["type"] == "text"
    assert fprops["synonyms"]["analyzer"] == _ASK_TEXT_ANALYZER


def test_rag_mapping_uses_the_same_analyzer():
    from ask_knowledge_graph.infrastructure.rag_vectorstore_client import _build_mapping

    body = _build_mapping(1024, language="es")
    assert body["mappings"]["properties"]["text"]["analyzer"] == _ASK_TEXT_ANALYZER
    assert body["settings"]["analysis"]["filter"]["ask_stop"]["stopwords"] == "_spanish_"
