# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""HANA adapter — uses a process-wide connection pool (see `hana_pool`).

Previously every SQL_EXECUTION request paid for a fresh hdbcli handshake.
With FastAPI now dispatching to a thread pool, that overhead dominated end-
to-end latency under concurrency. The adapter now acquires a connection
from `hana_pool.get_hana_pool(config)`, runs the query, and releases.
"""

from __future__ import annotations

import logging

from ..domain.errors import SqlExecutionError  # noqa: F401 — kept for re-export
from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_hana(request: ExecutionRequest) -> ExecutionResult:
    """Run SQL against SAP HANA via the pooled connection registry."""
    try:
        from .hana_pool import get_hana_pool  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        logger.warning("HANA pool unavailable: %s", exc)
        return ExecutionResult(success=False, error=f"HANA pool init failed: {exc}")

    try:
        pool = get_hana_pool(request.db_config)
        conn = pool.acquire()
    except Exception as exc:  # noqa: BLE001
        logger.warning("HANA pool acquire failed: %s", exc)
        return ExecutionResult(success=False, error=f"HANA connect failed: {exc}")

    success = False
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(request.sql)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
        finally:
            cursor.close()
        success = True
        return ExecutionResult(
            success=True,
            columns=columns,
            rows=rows,
            row_count=len(rows),
        )
    except Exception as exc:  # noqa: BLE001 — adapter boundary
        logger.warning("HANA execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
    finally:
        pool.release(conn, success=success)
