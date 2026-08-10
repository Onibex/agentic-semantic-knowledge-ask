"""Unit tests for SchemaResolverService — legacy SchemaCatalogService is stubbed."""

from __future__ import annotations

from ask_schema_service.application.schema_resolver import SchemaResolverService
from ask_schema_service.domain.models import SchemaQuery, SchemaResponse
from ask_schema_service.domain.ports import SchemaService


class _StubLegacy:
    def __init__(self, *, return_value: str | None = None, raises: Exception | None = None):
        self.calls: list[str] = []
        self.scopes: list[list[str] | None] = []
        self._return_value = return_value
        self._raises = raises

    def resolve_schema(self, question: str, allowed_ids: list[str] | None = None) -> str:
        self.calls.append(question)
        self.scopes.append(allowed_ids)
        if self._raises is not None:
            raise self._raises
        return self._return_value or ""


def test_protocol_satisfied():
    svc: SchemaService = SchemaResolverService(_StubLegacy())
    assert callable(svc.answer)


def test_happy_path_forwards_question_and_wraps_response():
    legacy = _StubLegacy(return_value="VBAK has 187 columns.")
    svc = SchemaResolverService(legacy)
    response = svc.answer(SchemaQuery(question="What columns does VBAK have?"))

    assert isinstance(response, SchemaResponse)
    assert response.answer == "VBAK has 187 columns."
    assert response.error is None
    assert legacy.calls == ["What columns does VBAK have?"]


def test_question_is_stripped_before_passing_to_legacy():
    legacy = _StubLegacy(return_value="ok")
    svc = SchemaResolverService(legacy)
    svc.answer(SchemaQuery(question="  How does VBAK relate to VBAP?  "))
    assert legacy.calls == ["How does VBAK relate to VBAP?"]


def test_empty_question_returns_error_without_invoking_legacy():
    legacy = _StubLegacy(return_value="should not be called")
    svc = SchemaResolverService(legacy)
    response = svc.answer(SchemaQuery(question=""))
    assert response.answer == ""
    assert response.error == "Empty schema question."
    assert legacy.calls == []


def test_whitespace_only_question_returns_error():
    legacy = _StubLegacy(return_value="should not be called")
    svc = SchemaResolverService(legacy)
    response = svc.answer(SchemaQuery(question="    "))
    assert response.error == "Empty schema question."
    assert legacy.calls == []


def test_legacy_exception_translates_to_error_response():
    legacy = _StubLegacy(raises=RuntimeError("OpenSearch unreachable"))
    svc = SchemaResolverService(legacy)
    response = svc.answer(SchemaQuery(question="anything"))
    assert response.error == "OpenSearch unreachable"
    assert "Pipeline error" in response.answer
    assert "OpenSearch unreachable" in response.answer


def test_legacy_returns_none_treated_as_empty_string():
    legacy = _StubLegacy(return_value=None)
    svc = SchemaResolverService(legacy)
    response = svc.answer(SchemaQuery(question="x"))
    assert response.answer == ""
    assert response.error is None


def test_workspace_scope_is_forwarded_to_legacy():
    """BACKLOG A/D1: `allowed_entity_ids` must reach the legacy catalog so the
    retrieval UNIVERSE is filtered (not the output) — an out-of-scope entity
    must never transit the LLM prompt."""
    legacy = _StubLegacy(return_value="ok")
    svc = SchemaResolverService(legacy)
    scope = ["silver_s4h_sd_sales_order", "bronze_s4h_vbak_order_header"]
    svc.answer(SchemaQuery(question="describe VBAK", allowed_entity_ids=scope))
    assert legacy.scopes == [scope]


def test_no_scope_stays_unscoped():
    """None (legacy/CLI callers) must forward as None — unscoped, not []."""
    legacy = _StubLegacy(return_value="ok")
    svc = SchemaResolverService(legacy)
    svc.answer(SchemaQuery(question="describe VBAK"))
    assert legacy.scopes == [None]
