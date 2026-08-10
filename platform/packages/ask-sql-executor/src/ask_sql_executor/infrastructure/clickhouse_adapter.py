"""ClickHouse adapter.

Driver: ``clickhouse-connect`` (official, HTTP). Install the extra:
``pip install ask-sql-executor[clickhouse]``.

Uses the connect native ``query()`` API (returns column_names + result_rows
directly), which is a hair simpler than a DB-API cursor and returns the same
columns/rows shape our service needs. db_config keys: host, port
(8443 TLS / 8123 plain), username, password, database, secure (bool),
final (bool).

``final``: when true, the ClickHouse ``final=1`` setting is applied PER QUERY
(best-effort) so SELECTs auto-add the FINAL modifier to MergeTree-family tables,
deduplicating ReplacingMergeTree/Collapsing/Aggregating at query time (otherwise
dedup is only eventual, on background merges → duplicate/stale rows). It costs
merge-on-read performance, so it is a config flag, not always-on. Some servers /
versions / read-only profiles reject the setting ("Setting final is unknown or
readonly"); we then retry WITHOUT it (query still succeeds, just no auto-dedup)
rather than breaking the query or the connection test. We do NOT emit FINAL in
the generated SQL (the model can't know each table's engine).
"""

from __future__ import annotations

import logging

from ..domain.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_clickhouse(request: ExecutionRequest) -> ExecutionResult:
    """Run a SQL statement against ClickHouse and return rows + columns."""
    try:
        import clickhouse_connect  # type: ignore[import-not-found]

        cfg = request.db_config
        client = clickhouse_connect.get_client(
            host=cfg["host"],
            port=int(cfg.get("port", 8443)),
            username=cfg.get("username", cfg.get("user", "default")),
            password=cfg.get("password", ""),
            database=cfg.get("database", "default"),
            secure=bool(cfg.get("secure", True)),
        )
        try:
            # `final=1` (opt-in) → FINAL auto-applied to MergeTree tables so
            # ReplacingMergeTree is deduplicated at query time. Applied PER QUERY
            # (not at connect) and best-effort: some servers/versions/read-only
            # profiles reject it ("Setting final is unknown or readonly") — in
            # that case retry WITHOUT it (works, just no auto-dedup) instead of
            # failing the query / the connection test.
            want_final = bool(cfg.get("final"))
            try:
                result = client.query(request.sql, settings={"final": 1} if want_final else None)
            except Exception as exc_final:  # noqa: BLE001 — setting-support probe
                if want_final and "final" in str(exc_final).lower():
                    logger.warning(
                        "ClickHouse 'final' setting not accepted (%s) — retrying without "
                        "auto-dedup; add FINAL in SQL or enable it server-side if needed.",
                        exc_final,
                    )
                    result = client.query(request.sql)
                else:
                    raise
            columns = list(result.column_names)
            rows = [tuple(r) for r in result.result_rows]
        finally:
            client.close()
        return ExecutionResult(success=True, columns=columns, rows=rows, row_count=len(rows))
    except Exception as exc:  # noqa: BLE001 — adapter boundary
        logger.warning("ClickHouse execution failed: %s", exc)
        return ExecutionResult(success=False, error=str(exc))
