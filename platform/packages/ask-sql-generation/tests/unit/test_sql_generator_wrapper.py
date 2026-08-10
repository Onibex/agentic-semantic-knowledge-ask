"""
Tests for FreeformSqlGenerator (the new dataclass-API wrapper over the
legacy FreeformSQLGeneratorService).

These tests stub out the legacy service to verify the request/response
mapping in isolation. End-to-end behavior with a real LLM is covered by
the benchmark (tests/benchmark/test_full_benchmark.py).
"""

from __future__ import annotations

import pytest

from ask_sql_generation.application.sql_generator import (
    FreeformSqlGenerator,
    _from_legacy_dict,
)
from ask_sql_generation.domain.errors import EmptyQuestionError, NoYamlsError
from ask_sql_generation.domain.models import (
    ScopeAudit,
    SqlGenerationRequest,
    SqlGenerationResult,
)


class _StubLegacyService:
    """Mimics FreeformSQLGeneratorService.generate(**kwargs) -> dict."""

    def __init__(self, return_value: dict) -> None:
        self.calls: list[dict] = []
        self._return = return_value

    def generate(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        return self._return


def _wrapper_with_stub(return_value: dict) -> tuple[FreeformSqlGenerator, _StubLegacyService]:
    stub = _StubLegacyService(return_value)
    wrapper = FreeformSqlGenerator(llm=object(), db_type="hana")
    wrapper._service = stub  # type: ignore[assignment]  # tests-only injection
    return wrapper, stub


def test_empty_question_raises_typed_error():
    wrapper, _ = _wrapper_with_stub({})
    with pytest.raises(EmptyQuestionError):
        wrapper.generate(SqlGenerationRequest(question="", yamls=["x"], db_type="hana"))


def test_empty_yamls_raises_typed_error():
    wrapper, _ = _wrapper_with_stub({})
    with pytest.raises(NoYamlsError):
        wrapper.generate(SqlGenerationRequest(question="how many?", yamls=[], db_type="hana"))


def test_happy_path_maps_legacy_dict_to_result():
    legacy_response = {
        "sql": 'SELECT count(*) FROM "X"',
        "table_name": "X",
        "scope_audit": {"ok": True, "out_of_scope": [], "in_scope": ["X"]},
    }
    wrapper, stub = _wrapper_with_stub(legacy_response)
    req = SqlGenerationRequest(
        question="how many X?",
        yamls=["id: silver_x"],
        db_type="hana",
        ir_hints={"intent_summary": "count"},
    )
    result = wrapper.generate(req)
    assert isinstance(result, SqlGenerationResult)
    assert result.sql == 'SELECT count(*) FROM "X"'
    assert result.error is None
    assert result.table_name == "X"
    assert result.scope_audit is not None and result.scope_audit.ok is True
    # The wrapper must have forwarded every kwarg the legacy service expects.
    forwarded = stub.calls[0]
    assert forwarded["question"] == "how many X?"
    assert forwarded["yamls"] == ["id: silver_x"]
    assert forwarded["ir_hints"] == {"intent_summary": "count"}
    assert forwarded["validate_scope"] is True
    assert forwarded["max_scope_retries"] == 1


def test_scope_warning_is_propagated():
    legacy_response = {
        "sql": 'SELECT * FROM "OOS_TABLE"',
        "scope_audit": {"ok": False, "out_of_scope": ["OOS_TABLE"], "in_scope": []},
        "scope_warning": "SQL references tables outside the curated scope",
    }
    wrapper, _ = _wrapper_with_stub(legacy_response)
    result = wrapper.generate(SqlGenerationRequest(question="x", yamls=["y"], db_type="hana"))
    assert result.scope_audit is not None
    assert result.scope_audit.ok is False
    assert "OOS_TABLE" in result.scope_audit.out_of_scope
    assert result.scope_warning is not None


def test_error_branch_maps_through():
    wrapper, _ = _wrapper_with_stub({"error": "LLM refused", "sql": None})
    result = wrapper.generate(SqlGenerationRequest(question="x", yamls=["y"], db_type="hana"))
    assert result.error == "LLM refused"
    assert result.sql is None


def test_need_more_context_flag():
    wrapper, _ = _wrapper_with_stub(
        {
            "need_more_context": True,
            "sql": None,
        }
    )
    result = wrapper.generate(
        SqlGenerationRequest(
            question="x",
            yamls=["y"],
            db_type="hana",
            context_expansion_enabled=True,
        )
    )
    assert result.need_more_context is True
    assert result.sql is None


def test_from_legacy_dict_handles_missing_fields():
    res = _from_legacy_dict({"sql": "SELECT 1"})
    assert res.sql == "SELECT 1"
    assert res.error is None
    assert res.scope_audit is None
    assert res.retry_count == 0


def test_scope_audit_dataclass_round_trip():
    audit_dict = {
        "ok": False,
        "out_of_scope": ["A", "B"],
        "in_scope": ["C"],
        "warnings": ["w1"],
    }
    res = _from_legacy_dict({"sql": "SELECT 1", "scope_audit": audit_dict})
    assert res.scope_audit == ScopeAudit(
        ok=False,
        out_of_scope=["A", "B"],
        in_scope=["C"],
        warnings=["w1"],
    )
