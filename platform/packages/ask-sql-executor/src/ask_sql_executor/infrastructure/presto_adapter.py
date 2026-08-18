# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Presto adapter (lite multi-DB).

Driver: ``presto-python-client`` (import name ``prestodb``). IBM watsonx.data's
Presto engine is genuine upstream PrestoDB, not Trino — it expects the legacy
``X-Presto-User``/``X-Presto-Catalog``/``X-Presto-Schema`` REST headers.
The ``trino`` client sends Trino's ``X-Trino-*`` headers instead, which a real
PrestoDB coordinator does not recognize (surfaces as a confusing
"User must be set" 400, even with a populated ``user`` field) — so ``trino``
is the wrong client here despite the protocol looking superficially identical.
Install the extra: ``pip install ask-sql-executor[presto]``.

For IBM Cloud IAM API-key auth (the common watsonx.data setup), set ``user``
to ``ibmlhapikey_<anything>`` and ``password`` to the IAM API key itself —
that ``ibmlhapikey_`` prefix is what tells the engine to treat the password
as an API key rather than a literal password.

db_config keys: host, port (default 8443 — watsonx.data's gateway commonly
uses 443), catalog, schema, user, password (optional — omit for
network-trust clusters with no auth), http_scheme (default "https").
"""

from __future__ import annotations

import logging

from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_presto(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against Presto and return rows + columns."""
    try:
        import prestodb  # type: ignore[import-not-found]

        cfg = request.db_config
        user = cfg.get("user", "")
        password = cfg.get("password", "")
        conn = prestodb.dbapi.connect(
            host=cfg["host"],
            port=int(cfg.get("port", 8443)),
            user=user,
            catalog=cfg.get("catalog", ""),
            schema=cfg.get("schema", ""),
            http_scheme=cfg.get("http_scheme", "https"),
            auth=prestodb.auth.BasicAuthentication(user, password) if password else None,
        )
        try:
            cursor = conn.cursor()
            cursor.execute(request.sql)
            rows = [tuple(row) for row in cursor.fetchall()]
            columns = [col[0] for col in cursor.description] if cursor.description else []
        finally:
            conn.close()
        return ExecutionResult(success=True, columns=columns, rows=rows, row_count=len(rows))
    except Exception as exc:  # noqa: BLE001 — adapter boundary
        logger.warning("Presto execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
