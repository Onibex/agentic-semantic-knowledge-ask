"""
SqlExecutorService — Iter 4 single entry point.

Replaces:
  - legacy/src/shared/db_executor.execute_sql_query
  - chat/sql_service.{execute_sql,format_results,no_results_answer}
  - ask_orchestrator.orchestration.legacy_adapter.execute_sql_only
"""

from __future__ import annotations

import logging

from ..domain.errors import UnsupportedDbTypeError
from ..domain.models import ExecutionRequest, ExecutionResult, FormattedResult
from ..domain.ports import ResultFormatter, SqlExecutor
from ..infrastructure.registry import get_adapter, supported_db_types

logger = logging.getLogger(__name__)


class SqlExecutorService(SqlExecutor):
    """Run SQL against any registered backend and format the rows.

    The backend adapter is selected from the execution registry
    (``infrastructure.registry``) keyed by ``request.db_type`` — a Strategy
    dispatch, so adding a backend is a registration, not an edit here. Holds a
    ResultFormatter so callers don't have to wire one every time.
    """

    def __init__(self, formatter: ResultFormatter) -> None:
        self._formatter = formatter

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        adapter = get_adapter(request.db_type)
        if adapter is None:
            raise UnsupportedDbTypeError(
                f"db_type={request.db_type!r} has no adapter (registered: {supported_db_types()})"
            )
        return adapter(request)

    def execute_and_format(self, request: ExecutionRequest, *, question: str) -> FormattedResult:
        raw = self.execute(request)
        if not raw.success:
            return FormattedResult(
                sql=request.sql,
                rows_dict=[],
                answer=f"Pipeline error: {raw.error}",
                error=raw.error,
                row_count=0,
            )

        if raw.row_count == 0:
            return FormattedResult(
                sql=request.sql,
                rows_dict=[],
                answer=self._formatter.no_results_answer(question, request.sql),
                error=None,
                row_count=0,
            )

        rows_dict = [dict(zip(raw.columns, r)) for r in raw.rows]
        answer = self._formatter.format_rows(raw.columns, raw.rows, question)
        return FormattedResult(
            sql=request.sql,
            rows_dict=rows_dict,
            answer=answer,
            error=None,
            row_count=raw.row_count,
        )
