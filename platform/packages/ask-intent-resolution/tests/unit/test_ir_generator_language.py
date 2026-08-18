# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The IR generator extracts terms in the SEMANTIC LAYER's language.

This is the load-bearing half of ASK_SEMANTIC_LANGUAGE (PLAN_SEMANTIC_LANGUAGE.md
W1): the extracted terms ARE the retrieval query, so they must be worded like the
corpus. Before the flag, the prompt hard-mandated English, which silently killed
the BM25 leg on a Spanish-authored layer.

The template-variable assertions are the regression guard for a real trap: the
system prompt is a ``ChatPromptTemplate`` source whose literal braces are doubled
(``{{"semantic_field": ...}}``). Interpolating the directive with an f-string
un-doubles all of them and turns every JSON example into a template variable.
"""

from __future__ import annotations

from ask_intent_resolution.precise.application.ir_generator import IRGeneratorService
from ask_knowledge_graph.domain.language import SemanticLanguage


def _system_template(svc: IRGeneratorService) -> str:
    return svc.prompt.messages[0].prompt.template


def _build(monkeypatch, value: str | None, *, isolate_cwd=None) -> IRGeneratorService:
    """Construct the service under a KNOWN language configuration.

    ``isolate_cwd`` moves the process to a directory with no
    ``config/settings.json``, so the "nothing configured" case really is that —
    the resolver is CWD-relative, and a test that skips this reads whatever the
    developer's deployment happens to be configured for."""
    if isolate_cwd is not None:
        monkeypatch.chdir(isolate_cwd)
    if value is None:
        monkeypatch.delenv("ASK_SEMANTIC_LANGUAGE", raising=False)
    else:
        monkeypatch.setenv("ASK_SEMANTIC_LANGUAGE", value)
    return IRGeneratorService(lambda x: x)


def test_defaults_to_english(monkeypatch, tmp_path):
    svc = _build(monkeypatch, None, isolate_cwd=tmp_path)
    assert svc.language is SemanticLanguage.EN
    assert "MUST be in ENGLISH" in _system_template(svc)


def test_spanish_deployment_extracts_in_spanish(monkeypatch):
    svc = _build(monkeypatch, "es")
    assert svc.language is SemanticLanguage.ES
    template = _system_template(svc)
    assert "MUST be in SPANISH" in template
    assert "ENGLISH" not in template
    assert "__LANGUAGE_RULE__" not in template  # placeholder fully substituted


def test_explicit_language_argument_wins(monkeypatch):
    monkeypatch.setenv("ASK_SEMANTIC_LANGUAGE", "en")
    svc = IRGeneratorService(lambda x: x, language=SemanticLanguage.ES)
    assert svc.language is SemanticLanguage.ES
    assert "MUST be in SPANISH" in _system_template(svc)


def test_prompt_keeps_exactly_its_three_template_variables(monkeypatch):
    """The JSON examples in the prompt must stay LITERAL braces, not variables."""
    svc = _build(monkeypatch, "es")
    assert set(svc.prompt.input_variables) == {
        "current_date",
        "format_instructions",
        "user_query",
    }


def test_json_examples_survive_as_literals(monkeypatch):
    svc = _build(monkeypatch, "es")
    rendered = svc.prompt.messages[0].prompt.format(
        current_date="2026-08-12", format_instructions="<schema>"
    )
    # A doubled brace in the template renders as ONE literal brace.
    assert '{"semantic_field": "country", "operator": "=", "value": "DE"}' in rendered
    assert "2026-08-12" in rendered
