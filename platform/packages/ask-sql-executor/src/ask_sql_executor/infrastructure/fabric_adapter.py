# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Microsoft Fabric (Warehouse / Lakehouse SQL analytics endpoint) adapter.

Driver: ``pyodbc`` + "ODBC Driver 18 for SQL Server" (system dep). Install the
extra: ``pip install ask-sql-executor[fabric]`` (same driver as sqlserver).

Fabric SQL endpoints are T-SQL over TDS but accept **Entra ID (Azure AD) only**
— no SQL user/password. This adapter uses the service-principal flow via ODBC
Driver 18. db_config keys: server (the ``<id>.datawarehouse.fabric.microsoft.com``
SQL connection string), database (warehouse / lakehouse name), tenant_id,
client_id, client_secret, driver.
"""

from __future__ import annotations

import logging

from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_fabric(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against a Fabric SQL endpoint and return rows + columns."""
    try:
        import pyodbc  # type: ignore[import-not-found]

        cfg = request.db_config
        driver = cfg.get("driver", "ODBC Driver 18 for SQL Server")
        # Service-principal auth: UID=client_id, PWD=client_secret. Some tenants
        # require the app id in the form <client_id>@<tenant_id>.
        uid = cfg["client_id"]
        if cfg.get("tenant_id") and "@" not in uid:
            uid = f"{uid}@{cfg['tenant_id']}"
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={cfg['server']};"
            f"DATABASE={cfg['database']};"
            f"Authentication=ActiveDirectoryServicePrincipal;"
            f"UID={uid};PWD={cfg['client_secret']};"
            f"Encrypt=yes;TrustServerCertificate=no;"
        )
        conn = pyodbc.connect(conn_str, timeout=int(cfg.get("connect_timeout", 30)))
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
        logger.warning("Fabric execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
