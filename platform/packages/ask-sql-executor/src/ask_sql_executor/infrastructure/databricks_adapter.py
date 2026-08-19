# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Databricks (SQL Warehouse) adapter — DB-API clone of the Postgres adapter.

Driver: ``databricks-sql-connector`` (PyPI). Install the extra:
``pip install ask-sql-executor[databricks]``.

Auth: Personal Access Token (default) or OAuth M2M. db_config keys:
server_hostname, http_path (the SQL warehouse path), access_token
(PAT) | client_id + client_secret (OAuth), catalog, schema.
"""

from __future__ import annotations

import logging

from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_databricks(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against a Databricks SQL Warehouse."""
    try:
        from databricks import sql as dbsql  # type: ignore[import-not-found]

        cfg = request.db_config
        kwargs: dict = {
            "server_hostname": cfg["server_hostname"],
            "http_path": cfg["http_path"],
            "access_token": cfg["access_token"],  # PAT (lite path); OAuth M2M is a later add
        }
        for key in ("catalog", "schema"):
            if cfg.get(key):
                kwargs[key] = cfg[key]

        conn = dbsql.connect(**kwargs)
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
        logger.warning("Databricks execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
