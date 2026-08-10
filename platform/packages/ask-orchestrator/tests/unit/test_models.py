import pytest
from pydantic import ValidationError

from ask_orchestrator.models.requests import QueryRequest
from ask_orchestrator.models.responses import ErrorResponse, QueryResponse


def test_query_request_defaults():
    req = QueryRequest(question="how many open POs?", workspace_id="ws-test")
    assert req.mode == "precise"
    assert req.session_id is None
    assert req.conversation_history is None
    assert req.workspace_id == "ws-test"


def test_query_request_rejects_unknown_mode():
    with pytest.raises(ValidationError):
        QueryRequest(question="x", workspace_id="ws-test", mode="turbo")  # type: ignore[arg-type]


def test_query_request_rejects_empty_question():
    with pytest.raises(ValidationError):
        QueryRequest(question="", workspace_id="ws-test")


def test_query_request_rejects_missing_workspace():
    """Iter 1 (Req #5): workspace_id is required."""
    with pytest.raises(ValidationError) as exc_info:
        QueryRequest(question="x")  # type: ignore[call-arg]
    assert "workspace_id" in str(exc_info.value)


def test_query_response_minimal():
    resp = QueryResponse(
        answer="42",
        macro_intent="SQL_EXECUTION",
        mode_used="precise",
        trace_id="abc-123",
    )
    assert resp.rows is None
    assert resp.sql is None
    assert resp.tokens_used is None


def test_query_response_rejects_unknown_macro_intent():
    with pytest.raises(ValidationError):
        QueryResponse(
            answer="x",
            macro_intent="TRAINING",  # type: ignore[arg-type]
            mode_used="precise",
            trace_id="t",
        )


def test_error_response_shape():
    err = ErrorResponse(error_code="LEGACY_FAILURE", message="boom", trace_id="t")
    assert err.error_code == "LEGACY_FAILURE"
