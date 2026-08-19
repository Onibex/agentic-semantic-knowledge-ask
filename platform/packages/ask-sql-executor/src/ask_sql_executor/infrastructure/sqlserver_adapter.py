# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Microsoft SQL Server (T-SQL) adapter.

Driver: ``pyodbc`` (PyPI) + the system ODBC driver
"ODBC Driver 18 for SQL Server" (must be present in the runtime image).
Install the extra: ``pip install ask-sql-executor[sqlserver]``.

db_config keys: host, port (1433), database, user, password, driver,
encrypt (yes/no), trust_server_certificate (yes/no).
"""

from __future__ import annotations

import logging

from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_sqlserver(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against SQL Server and return rows + columns."""
    try:
        import pyodbc  # type: ignore[import-not-found]

        cfg = request.db_config
        driver = cfg.get("driver", "ODBC Driver 18 for SQL Server")
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={cfg['host']},{int(cfg.get('port', 1433))};"
            f"DATABASE={cfg['database']};"
            f"UID={cfg['user']};PWD={cfg['password']};"
            f"Encrypt={cfg.get('encrypt', 'yes')};"
            f"TrustServerCertificate={cfg.get('trust_server_certificate', 'yes')};"
        )
        conn = pyodbc.connect(conn_str, timeout=int(cfg.get("connect_timeout", 15)))
        try:
            cursor = conn.cursor()
            cursor.execute(request.sql)
            columns = [desc[0] for desc in cursor.description]
            rows = [tuple(r) for r in cursor.fetchall()]
            cursor.close()
        finally:
            conn.close()
        return ExecutionResult(success=True, columns=columns, rows=rows, row_count=len(rows))
    except Exception as exc:  # noqa: BLE001 — adapter boundary
        logger.warning("SQL Server execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
