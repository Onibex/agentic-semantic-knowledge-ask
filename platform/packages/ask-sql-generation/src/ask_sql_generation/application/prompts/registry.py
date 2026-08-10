"""Dialect-prompt registry (Strategy pattern) — lite multi-DB, 2026-07.

The "dialect axis" of the two-axis design (internal design doc
ITERATION_MULTI_DB_ARCHITECTURE); the "execution axis" is
``ask_sql_executor.infrastructure.registry``.

Each ``prompts/<db>.py`` module exports:
  - ``ROLE_LINE``      — the "You are a <dialect> expert…" line.
  - ``STRICT_RULES``   — the per-dialect rules block appended to the prompt.
  - ``schema_prefix_rule(schema)`` — OPTIONAL; returns a mandatory
    schema-qualification block when a schema/dataset is configured.

Keeping per-dialect prompt MODULES (not one parametrized prompt) is the
deliberate "lite" choice: the Strategy/registry gives clean extensibility while
the dialect rules stay explicit and reviewable. Consolidation into a capability
descriptor is the post-MVP1 refactor.

The bulk of each dialect's rules is shared SAP data-model semantics (VARCHAR
date sentinels, medallion CTE casing, etc.); only the mechanical ~20% (quoting,
row-limiting, date functions, string aggregation) actually differs per dialect.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class DialectPrompt:
    """The three prompt pieces the generator needs for one dialect."""

    role_line: str
    strict_rules: str
    schema_prefix: Callable[[str], str] | None = None


_DIALECTS: dict[str, DialectPrompt] = {}
_LOADED = False


def register_dialect(db_type: str, prompt: DialectPrompt) -> None:
    """Register (or override) the prompt for ``db_type``. Exposed for tests /
    out-of-tree extensions."""
    _DIALECTS[db_type] = prompt


def _reg_module(db_type: str, module) -> None:
    _DIALECTS.setdefault(
        db_type,
        DialectPrompt(
            role_line=module.ROLE_LINE,
            strict_rules=module.STRICT_RULES,
            schema_prefix=getattr(module, "schema_prefix_rule", None),
        ),
    )


def _autoload() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    from . import (
        bigquery,
        clickhouse,
        databricks,
        db2,
        fabric,
        hana,
        postgresql,
        snowflake,
        sqlserver,
    )

    _reg_module("hana", hana)
    _reg_module("postgresql", postgresql)
    _reg_module("snowflake", snowflake)
    _reg_module("databricks", databricks)
    _reg_module("clickhouse", clickhouse)
    _reg_module("sqlserver", sqlserver)
    _reg_module("db2", db2)
    _reg_module("bigquery", bigquery)
    _reg_module("fabric", fabric)


def get_dialect(db_type: str) -> DialectPrompt | None:
    """Return the DialectPrompt for ``db_type`` or ``None`` if unregistered."""
    _autoload()
    return _DIALECTS.get(db_type)


def supported_dialects() -> list[str]:
    """Sorted list of db_types with a registered dialect prompt."""
    _autoload()
    return sorted(_DIALECTS)


__all__ = [
    "DialectPrompt",
    "register_dialect",
    "get_dialect",
    "supported_dialects",
]
