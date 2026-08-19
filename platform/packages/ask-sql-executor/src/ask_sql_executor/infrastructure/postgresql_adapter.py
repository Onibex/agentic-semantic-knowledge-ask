# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""PostgreSQL adapter — lifts the postgres branch from legacy/src/shared/db_executor."""

from __future__ import annotations

import logging

from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_postgresql(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against PostgreSQL and return rows + columns."""
    try:
        import psycopg2  # type: ignore[import-not-found]

        cfg = request.db_config
        conn = psycopg2.connect(
            host=cfg["host"],
            port=cfg["port"],
            database=cfg["database"],
            user=cfg["user"],
            password=cfg["password"],
            sslmode=cfg.get("sslmode", "prefer"),
        )
        try:
            cursor = conn.cursor()
            cursor.execute(request.sql)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            cursor.close()
        finally:
            conn.close()
        return ExecutionResult(
            success=True,
            columns=columns,
            rows=rows,
            row_count=len(rows),
        )
    except Exception as exc:  # noqa: BLE001 — adapter boundary
        logger.warning("PostgreSQL execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
