# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""ClickHouse adapter.

Driver: ``clickhouse-connect`` (official, HTTP). Install the extra:
``pip install ask-sql-executor[clickhouse]``.

Uses the connect native ``query()`` API (returns column_names + result_rows
directly), which is a hair simpler than a DB-API cursor and returns the same
columns/rows shape our service needs. db_config keys: host, port
(8443 TLS / 8123 plain), username, password, database, secure (bool),
final (bool).

``final``: when true, the ClickHouse ``final=1`` setting is applied PER QUERY
so SELECTs auto-add the FINAL modifier to MergeTree-family tables,
deduplicating ReplacingMergeTree/Collapsing/Aggregating at query time (otherwise
dedup is only eventual, on background merges → duplicate/stale rows). It costs
merge-on-read performance, so it is a config flag, not always-on.

Some servers reject the setting: 22.1 does not know it ("Unknown setting
final"), and a read-only profile may not change it. The adapter then inserts
FINAL itself, after each table whose engine supports it, as reported by
``system.tables`` (see ``clickhouse_final``). Until 2026-10-12 it retried with
no deduplication at all, which on the GONAC server (22.1) counted every
unmerged version of a row. The model still never writes FINAL: it cannot know
each table's engine, and a View or a plain MergeTree rejects the modifier.

When the statement had to be rewritten, ``ExecutionResult.executed_sql``
carries the SQL that actually ran, so the answer shows a query that reproduces
its numbers.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from ..domain.models import ExecutionRequest, ExecutionResult
from .clickhouse_final import add_final, find_table_refs, supports_final

logger = logging.getLogger(__name__)

# The wording of a server that does not take the setting, as opposed to a query
# error that happens to mention "final" (a column named final_qty, say).
_SETTING_REJECTED = re.compile(
    r"unknown setting final|setting final is unknown|cannot modify 'final' setting",
    re.IGNORECASE,
)

# (host, port, username) of the servers known to reject ``final=1``, so each
# query does not pay a failed round trip first. Process lifetime: a server
# upgraded to a version that takes the setting is picked up on restart.
_rejects_setting: set[tuple[str, int, str]] = set()

# (host, port, database, table) -> (engine, expiry). Tables that were not found
# are cached as "" too, so a CTE name is not looked up on every question.
_ENGINE_TTL_SECONDS = 300.0
_engine_cache: dict[tuple[str, int, str, str], tuple[str, float]] = {}


def execute_clickhouse(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against ClickHouse and return rows + columns."""
    try:
        import clickhouse_connect  # type: ignore[import-not-found]

        cfg = request.db_config
        host, port = cfg["host"], int(cfg.get("port", 8443))
        username = cfg.get("username", cfg.get("user", "default"))
        client = clickhouse_connect.get_client(
            host=host,
            port=port,
            username=username,
            password=cfg.get("password", ""),
            database=cfg.get("database", "default"),
            secure=bool(cfg.get("secure", True)),
        )
        try:
            executed_sql: str | None = None
            server = (host, port, username)
            if not cfg.get("final"):
                result = client.query(request.sql)
            elif server in _rejects_setting:
                result, executed_sql = _query_with_explicit_final(client, request.sql, cfg)
            else:
                try:
                    result = client.query(request.sql, settings={"final": 1})
                except Exception as exc_final:  # noqa: BLE001 - setting-support probe
                    if "final" not in str(exc_final).lower():
                        raise
                    if _SETTING_REJECTED.search(str(exc_final)):
                        _rejects_setting.add(server)
                    logger.warning(
                        "ClickHouse 'final' setting not accepted (%s); adding FINAL to the "
                        "tables whose engine supports it instead.",
                        exc_final,
                    )
                    result, executed_sql = _query_with_explicit_final(client, request.sql, cfg)
            columns = list(result.column_names)
            rows = [tuple(r) for r in result.result_rows]
        finally:
            client.close()
        return ExecutionResult(
            success=True,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            executed_sql=executed_sql,
        )
    except Exception as exc:  # noqa: BLE001 — adapter boundary
        logger.warning("ClickHouse execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))


def _query_with_explicit_final(
    client: Any, sql: str, cfg: dict[str, Any]
) -> tuple[Any, str | None]:
    """Run ``sql`` with FINAL after each table that supports it.

    Returns the result and the rewritten SQL, or ``None`` when it ran as given.
    Never worse than running it as given: a failed lookup skips the rewrite,
    and a rewrite the server refuses for any reason is retried unmodified.
    """
    refs = [r for r in find_table_refs(sql) if not r.has_final]
    if not refs:
        return client.query(sql), None
    default_db = cfg.get("database") or "default"
    try:
        engines = _table_engines(
            client, cfg["host"], int(cfg.get("port", 8443)),
            {(r.database or default_db, r.name) for r in refs},
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - degrade to the pre-2026-10 behaviour
        logger.warning("ClickHouse engine lookup failed (%s); running without FINAL.", exc)
        return client.query(sql), None
    targets = [r for r in refs if supports_final(engines.get((r.database or default_db, r.name)))]
    if not targets:
        return client.query(sql), None
    rewritten = add_final(sql, targets)
    try:
        return client.query(rewritten), rewritten
    except Exception as exc:  # noqa: BLE001 - the original SQL decides the outcome
        logger.warning("ClickHouse refused the FINAL rewrite (%s); running it as generated.", exc)
        return client.query(sql), None


def _table_engines(
    client: Any, host: str, port: int, tables: set[tuple[str, str]]
) -> dict[tuple[str, str], str]:
    """``{(database, table): engine}``, "" for a name that is not a table."""
    now = time.monotonic()
    engines: dict[tuple[str, str], str] = {}
    missing: list[tuple[str, str]] = []
    for db, name in tables:
        hit = _engine_cache.get((host, port, db, name))
        if hit and hit[1] > now:
            engines[(db, name)] = hit[0]
        else:
            missing.append((db, name))
    if missing:
        wanted = ", ".join(f"({_literal(db)}, {_literal(name)})" for db, name in sorted(missing))
        result = client.query(
            f"SELECT database, name, engine FROM system.tables WHERE (database, name) IN ({wanted})"
        )
        found = {(row[0], row[1]): row[2] for row in result.result_rows}
        for key in missing:
            engines[key] = found.get(key, "")
            _engine_cache[(host, port, *key)] = (engines[key], now + _ENGINE_TTL_SECONDS)
    return engines


def _literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
