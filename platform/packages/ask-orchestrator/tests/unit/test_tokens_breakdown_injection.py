# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: EVERY return path out of ``run_query_pipeline`` must carry the
per-request token breakdown.

The bug this pins
─────────────────
The ACTION_EXECUTION branch did ``return _handle_action_execution(...)`` from
inside its own try block, jumping over the injection at the end of the function.
Result: ACTION_EXECUTION responses ALWAYS shipped ``tokens_used=None,
tokens_breakdown=None`` — even though macro classification is itself an LLM call
that the tracker had already recorded.

Every request records at least one call for exactly that reason, so a ``None``
breakdown on any non-error path is a bug, not an "untracked path".
"""

from __future__ import annotations

import pytest

from ask_orchestrator.models.requests import QueryRequest
from ask_orchestrator.models.responses import QueryResponse
from ask_orchestrator.routers import query as query_router

_USER = {"email": "tester@onibex.com", "bypass": True}


def _request(question: str = "create sales order for customer 1000") -> QueryRequest:
    return QueryRequest(question=question, workspace_id="ws-1", mode="smart", env="dev")


def _stub_classifier(monkeypatch, intent: str) -> None:
    """Classify without an LLM, but still record a tracked call — that is what
    the real MacroIntentClassifier does (it is a prompt|llm|parser chain), and it
    is why the breakdown is never legitimately None."""
    from ask_llm_gateway.infrastructure.token_tracker import get_active_tracker

    def _classify(_question: str) -> str:
        tracker = get_active_tracker()
        assert tracker is not None, "pipeline must install a tracker before classifying"
        tracker.record(
            phase="macro_classification",
            model="stub-model",
            input_tokens=120,
            output_tokens=8,
        )
        return intent

    monkeypatch.setattr(query_router._classifier, "classify", _classify)


class _StubActionService:
    def execute(self, _request):
        from ask_action_execution.domain.models import ActionResponse

        return ActionResponse(answer="Sales order 0000012345 created.")


def test_action_execution_response_carries_the_tokens_breakdown(monkeypatch):
    """The regression: this path used to return early and always ship None."""
    _stub_classifier(monkeypatch, "ACTION_EXECUTION")
    monkeypatch.setattr(query_router, "_get_action_service", lambda: _StubActionService())

    response = query_router.run_query_pipeline(_request(), _USER)

    assert response.macro_intent == "ACTION_EXECUTION"
    assert response.tokens_breakdown is not None, "ACTION_EXECUTION dropped the breakdown"
    assert response.tokens_breakdown.total_calls == 1
    assert response.tokens_breakdown.total_tokens == 128
    assert response.tokens_used == 128
    assert "macro_classification" in response.tokens_breakdown.by_phase


def test_action_execution_breakdown_survives_the_handler_reporting_no_tokens(monkeypatch):
    """``_handle_action_execution`` hardcodes ``tokens_used=None``. The injection
    must overwrite it from the tracker rather than trust the handler."""
    _stub_classifier(monkeypatch, "ACTION_EXECUTION")
    monkeypatch.setattr(query_router, "_get_action_service", lambda: _StubActionService())

    raw = query_router._handle_action_execution(_request(), "trace-1")
    assert raw.tokens_used is None  # handler's own value

    response = query_router.run_query_pipeline(_request(), _USER)
    assert response.tokens_used == 128  # tracker wins


def test_sql_path_still_carries_the_breakdown(monkeypatch):
    """Guard against the refactor to ``_with_tokens`` regressing the path that
    already worked."""
    _stub_classifier(monkeypatch, "SQL_EXECUTION")

    class _StubScope:
        def get_entity_ids(self, _ws, env=None):
            return ["silver_s4h_sd_sales_order"]

        def get_schema_entity_ids(self, _ws, env=None):
            return ["silver_s4h_sd_sales_order"]

    from ask_orchestrator import workspace_scope

    monkeypatch.setattr(workspace_scope, "_provider", _StubScope())

    def _handler(req, macro_intent, trace_id):
        return QueryResponse(
            answer="42",
            macro_intent=macro_intent,
            mode_used=req.mode,
            trace_id=trace_id,
            tokens_used=None,
        )

    monkeypatch.setattr(query_router, "_handle_sql_execution", _handler)

    response = query_router.run_query_pipeline(_request("how many orders"), _USER)
    assert response.tokens_breakdown is not None
    assert response.tokens_used == 128


def test_breakdown_is_none_only_when_nothing_was_tracked(monkeypatch):
    """The one legitimate None: a classifier that records no call at all. Keeps
    ``_build_tokens_breakdown``'s guard honest instead of fabricating zeros."""
    monkeypatch.setattr(query_router._classifier, "classify", lambda _q: "ACTION_EXECUTION")
    monkeypatch.setattr(query_router, "_get_action_service", lambda: _StubActionService())

    response = query_router.run_query_pipeline(_request(), _USER)
    assert response.tokens_breakdown is None
    assert response.tokens_used is None


def test_tracker_is_cleared_after_the_action_path(monkeypatch):
    """The tracker lives in a contextvar; leaking it would attribute the next
    request's calls to this one."""
    from ask_llm_gateway.infrastructure.token_tracker import get_active_tracker

    _stub_classifier(monkeypatch, "ACTION_EXECUTION")
    monkeypatch.setattr(query_router, "_get_action_service", lambda: _StubActionService())

    query_router.run_query_pipeline(_request(), _USER)
    assert get_active_tracker() is None


def test_action_execution_failure_still_raises_http_500(monkeypatch):
    """The injection must not swallow handler failures."""
    from fastapi import HTTPException

    _stub_classifier(monkeypatch, "ACTION_EXECUTION")

    class _Boom:
        def execute(self, _request):
            raise RuntimeError("MCP unreachable")

    monkeypatch.setattr(query_router, "_get_action_service", lambda: _Boom())

    with pytest.raises(HTTPException) as exc:
        query_router.run_query_pipeline(_request(), _USER)
    assert exc.value.status_code == 500
    assert exc.value.detail["error_code"] == "PIPELINE_ERROR"
