"""Execution-adapter registry (Strategy pattern) — lite multi-DB, 2026-07.

Replaces the hard-coded ``if/elif`` dispatch in ``executor_service.py`` with a
single lookup keyed by ``db_type``. Adding a backend is now a registration, not
an edit to the service.

Each adapter is a plain function ``execute_<db>(request) -> ExecutionResult`` that
**lazy-imports its driver inside the function**, so importing an adapter module is
cheap and never requires the driver to be installed until that backend is used.

This is the "execution axis" of the two-axis design (internal design doc
ITERATION_MULTI_DB_ARCHITECTURE). The "dialect axis" lives in
``ask_sql_generation.application.prompts.registry``.
"""

from __future__ import annotations

from collections.abc import Callable

from ..domain.models import ExecutionRequest, ExecutionResult

AdapterFn = Callable[[ExecutionRequest], ExecutionResult]

_ADAPTERS: dict[str, AdapterFn] = {}
_LOADED = False


def register_adapter(db_type: str, fn: AdapterFn) -> None:
    """Register (or override) the adapter for ``db_type``. Exposed for tests /
    out-of-tree extensions."""
    _ADAPTERS[db_type] = fn


def _autoload() -> None:
    """Populate the registry from the built-in adapter modules once.

    Imports are done here (not at module top) so the registry module itself has
    no import-time driver dependencies; each adapter module lazy-imports its own
    driver inside its ``execute_*`` function.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    from . import (
        bigquery_adapter,
        clickhouse_adapter,
        databricks_adapter,
        db2_adapter,
        fabric_adapter,
        hana_adapter,
        postgresql_adapter,
        presto_adapter,
        snowflake_adapter,
        sqlserver_adapter,
    )

    _ADAPTERS.setdefault("hana", hana_adapter.execute_hana)
    _ADAPTERS.setdefault("postgresql", postgresql_adapter.execute_postgresql)
    _ADAPTERS.setdefault("snowflake", snowflake_adapter.execute_snowflake)
    _ADAPTERS.setdefault("databricks", databricks_adapter.execute_databricks)
    _ADAPTERS.setdefault("clickhouse", clickhouse_adapter.execute_clickhouse)
    _ADAPTERS.setdefault("sqlserver", sqlserver_adapter.execute_sqlserver)
    _ADAPTERS.setdefault("db2", db2_adapter.execute_db2)
    _ADAPTERS.setdefault("bigquery", bigquery_adapter.execute_bigquery)
    _ADAPTERS.setdefault("fabric", fabric_adapter.execute_fabric)
    _ADAPTERS.setdefault("presto", presto_adapter.execute_presto)


def get_adapter(db_type: str) -> AdapterFn | None:
    """Return the adapter for ``db_type`` or ``None`` if unregistered."""
    _autoload()
    return _ADAPTERS.get(db_type)


def supported_db_types() -> list[str]:
    """Sorted list of db_types with a registered execution adapter."""
    _autoload()
    return sorted(_ADAPTERS)


__all__ = ["register_adapter", "get_adapter", "supported_db_types", "AdapterFn"]
