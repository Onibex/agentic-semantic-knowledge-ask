"""Domain contract tests for ask-sql-generation."""

from __future__ import annotations

from ask_sql_generation.domain.errors import (
    EmptyQuestionError,
    LLMInvocationError,
    NoYamlsError,
    SqlGenerationError,
)
from ask_sql_generation.domain.models import (
    ScopeAudit,
    SqlGenerationRequest,
    SqlGenerationResult,
)
from ask_sql_generation.domain.ports import LLMPort, SqlGenerator


def test_request_minimal_construction():
    req = SqlGenerationRequest(
        question="how many open POs?",
        yamls=["id: silver_x"],
        db_type="hana",
    )
    assert req.validate_scope is True
    assert req.max_scope_retries == 1
    assert req.glossary == ""
    assert req.ir_hints == {}


def test_result_happy_path():
    res = SqlGenerationResult(
        sql="SELECT 1",
        error=None,
        scope_audit=ScopeAudit(ok=True),
        tokens_used=120,
    )
    assert res.sql == "SELECT 1"
    assert res.error is None
    assert res.scope_audit.ok is True
    assert res.retry_count == 0


def test_result_error_path():
    res = SqlGenerationResult(sql=None, error="No YAMLs supplied")
    assert res.sql is None
    assert res.error == "No YAMLs supplied"


def test_scope_audit_defaults():
    audit = ScopeAudit(ok=False)
    assert audit.out_of_scope == []
    assert audit.in_scope == []


def test_error_hierarchy():
    assert issubclass(EmptyQuestionError, SqlGenerationError)
    assert issubclass(NoYamlsError, SqlGenerationError)
    assert issubclass(LLMInvocationError, SqlGenerationError)


def test_protocol_satisfied_by_simple_class():
    class _OK:
        def generate(self, request: SqlGenerationRequest) -> SqlGenerationResult:
            return SqlGenerationResult(sql="SELECT 1", error=None)

    instance: SqlGenerator = _OK()
    assert callable(instance.generate)


def test_llm_port_declares_chat():
    assert "chat" in dir(LLMPort)
