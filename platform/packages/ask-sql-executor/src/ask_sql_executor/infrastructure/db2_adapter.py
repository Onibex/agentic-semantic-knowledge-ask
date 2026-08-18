# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""IBM Db2 adapter.

Driver: ``ibm-db`` (PyPI; exposes the DB-API 2.0 wrapper ``ibm_db_dbi``).
Install the extra: ``pip install ask-sql-executor[db2]``. The wheel bundles the
native Db2 CLI driver — validate on the actual deploy image (musl/Alpine can
fail the native-lib step).

db_config keys: host, port (50000 plain / 50001 or 443 SSL), database, user,
password, security ("SSL" for Db2 on Cloud / Warehouse).
"""

from __future__ import annotations

import logging

from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_db2(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against IBM Db2 and return rows + columns."""
    try:
        import ibm_db_dbi  # type: ignore[import-not-found]

        cfg = request.db_config
        conn_str = (
            f"DATABASE={cfg['database']};"
            f"HOSTNAME={cfg['host']};"
            f"PORT={int(cfg.get('port', 50000))};"
            f"PROTOCOL=TCPIP;"
            f"UID={cfg['user']};PWD={cfg['password']};"
        )
        if str(cfg.get("security", "")).upper() == "SSL":
            conn_str += "SECURITY=SSL;"
            if cfg.get("ssl_server_certificate"):
                conn_str += f"SSLServerCertificate={cfg['ssl_server_certificate']};"

        conn = ibm_db_dbi.connect(conn_str, "", "")
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
        logger.warning("Db2 execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
