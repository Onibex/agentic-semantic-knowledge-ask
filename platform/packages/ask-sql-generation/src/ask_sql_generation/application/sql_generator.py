"""
Concrete implementation of the SqlGenerator Protocol.

Wraps the legacy FreeformSQLGeneratorService (kept verbatim in
freeform_generator.py — it is the production-tested code) and adapts its
loose-kwargs API to the SqlGenerationRequest / SqlGenerationResult
dataclasses defined in domain.models.

The wrapper intentionally does not change behavior: every parameter the
legacy service accepted is forwarded, every dict field the legacy service
returned is mapped onto SqlGenerationResult fields.
"""

from __future__ import annotations

from typing import Any

from ..domain.errors import EmptyQuestionError, NoYamlsError
from ..domain.models import (
    ScopeAudit,
    SqlGenerationRequest,
    SqlGenerationResult,
)
from ..domain.ports import SqlGenerator
from .freeform_generator import FreeformSQLGeneratorService


class FreeformSqlGenerator(SqlGenerator):
    """SqlGenerator implementation backed by the legacy FreeformSQLGeneratorService.

    Construct once per (llm, db_type) pair and reuse — no per-request state.
    """

    def __init__(self, llm: Any, db_type: str = "hana") -> None:
        self._service = FreeformSQLGeneratorService(llm=llm, db_type=db_type)
        self._db_type = (db_type or "hana").lower()

    def generate(self, request: SqlGenerationRequest) -> SqlGenerationResult:
        if not request.question or not request.question.strip():
            raise EmptyQuestionError("question must not be empty")
        if not request.yamls:
            raise NoYamlsError(
                "no YAMLs supplied — IntentResolution did not provide schema context"
            )

        legacy_dict = self._service.generate(
            question=request.question,
            ir_hints=request.ir_hints,
            yamls=request.yamls,
            glossary=request.glossary,
            conversation_history=request.conversation_history,
            pg_sap_rules=request.pg_sap_rules,
            user_system_prompt=request.user_system_prompt,
            field_enrichments=request.field_enrichments or None,
            edges=request.edges or None,
            resolved_paths=request.resolved_paths or None,
            validate_scope=request.validate_scope,
            max_scope_retries=request.max_scope_retries,
            connectivity=request.connectivity or None,
            context_expansion_enabled=request.context_expansion_enabled,
            hana_schema=request.hana_schema,
        )
        return _from_legacy_dict(legacy_dict)


def _from_legacy_dict(d: dict[str, Any]) -> SqlGenerationResult:
    """Map the legacy service's dict return value onto SqlGenerationResult."""
    audit_dict = d.get("scope_audit")
    audit = (
        ScopeAudit(
            ok=bool(audit_dict.get("ok", False)),
            out_of_scope=list(audit_dict.get("out_of_scope") or []),
            in_scope=list(audit_dict.get("in_scope") or []),
            warnings=list(audit_dict.get("warnings") or []),
        )
        if isinstance(audit_dict, dict)
        else None
    )
    return SqlGenerationResult(
        sql=d.get("sql"),
        error=d.get("error"),
        scope_audit=audit,
        scope_warning=d.get("scope_warning"),
        need_more_context=bool(d.get("need_more_context", False)),
        table_name=d.get("table_name"),
        retry_count=int(d.get("retry_count", 0)),
        tokens_used=d.get("tokens_used"),
        raw_response=d.get("raw_response"),
    )
