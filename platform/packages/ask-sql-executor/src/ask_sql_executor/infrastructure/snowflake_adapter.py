# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Snowflake adapter — DB-API clone of the Postgres adapter.

Driver: ``snowflake-connector-python`` (PyPI). Install the extra:
``pip install ask-sql-executor[snowflake]``.

Auth: password OR key-pair JWT. Snowflake blocks single-factor password sign-in
for service users, so ``private_key_file`` (+ ``authenticator='snowflake_jwt'``)
is the production path. db_config keys: account, user, password |
private_key_file (+ private_key_passphrase), warehouse, database, schema, role.
"""

from __future__ import annotations

import logging

from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_snowflake(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against Snowflake and return rows + columns."""
    try:
        import snowflake.connector  # type: ignore[import-not-found]

        cfg = request.db_config
        kwargs: dict = {"account": cfg["account"], "user": cfg["user"]}
        if cfg.get("private_key_file"):
            kwargs["private_key_file"] = cfg["private_key_file"]
            kwargs["authenticator"] = cfg.get("authenticator", "snowflake_jwt")
            if cfg.get("private_key_passphrase"):
                kwargs["private_key_file_pwd"] = cfg["private_key_passphrase"]
        elif cfg.get("password"):
            kwargs["password"] = cfg["password"]
        for key in ("warehouse", "database", "schema", "role"):
            if cfg.get(key):
                kwargs[key] = cfg[key]

        conn = snowflake.connector.connect(**kwargs)
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
        logger.warning("Snowflake execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
