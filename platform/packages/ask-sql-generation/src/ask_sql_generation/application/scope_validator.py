# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
src/pipeline/application/sql_scope_validator.py

Plan v1 #3 — Scope validation for the semi-deterministic SQL pipeline.

The freeform SQL generator sees the full YAMLs of every entity curated by
Phases 2-3 and writes SQL on top of them. Nothing today prevents the LLM
from referencing a physical table that is not in the curated scope — e.g.
hallucinating a bronze SAP table that only appears in `composed_of` lineage
metadata, or picking up a table name from a sibling YAML that wasn't meant
to be used.

This module:
  1. Extracts the authoritative `allowed_tables` set from the raw YAMLs
     supplied to the generator (the single denormalized `db_table_name`
     per Silver/Gold entity — same convention the prompt's YAML_READING
     block already enforces).
  2. Parses the generated SQL with a conservative regex to pull out the
     physical tables referenced after FROM/JOIN/INTO/UPDATE, filtering
     out CTE self-references (names defined in `WITH <name> AS (...)`).
  3. Reports any out-of-scope tables so the caller can trigger a retry
     with explicit feedback to the LLM.

Columns are intentionally NOT validated here — the generator aliases
columns freely (AS "some_alias") and a regex pass would produce too many
false positives. Table-level validation catches the most damaging class
of hallucinations without blocking the SQL generator on style nits.

Non-destructive: the validator only REPORTS; the caller decides whether
to retry, warn, or accept.
"""

from __future__ import annotations

import re
from typing import Any

from ruamel.yaml import YAML


def _load_yaml(text: str) -> Any:
    """Parse YAML 1.2 (ruamel). Unlike PyYAML's YAML 1.1, bare tokens such as
    On/Off/Yes/No stay strings — the whole codebase uses one parser."""
    if not text or not text.strip():
        return None
    return YAML(typ="safe").load(text)


# ─────────────────────────────────────────────────────────────────────────────
# Scope extraction
# ─────────────────────────────────────────────────────────────────────────────


def build_allowed_tables(yamls: list[str]) -> set[str]:
    """
    Build the authoritative set of physical table names allowed in the SQL,
    reading `db_table_name` from each raw YAML. Falls back to the entity
    `name` field if `db_table_name` is absent. Table names are uppercased
    to match SAP HANA identifier folding.
    """
    allowed: set[str] = set()
    for raw in yamls or []:
        if not raw or not raw.strip():
            continue
        try:
            parsed = _load_yaml(raw)
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        tbl = parsed.get("db_table_name") or parsed.get("name")
        if tbl:
            allowed.add(str(tbl).upper())
    return allowed


def build_entity_table_map(yamls: list[str]) -> dict[str, str]:
    """``{entity_id: db_table_name}`` for the retrieved YAMLs.

    Sibling of :func:`build_allowed_tables` — same source, same parse, different
    shape: that one needs the anonymous SET of legal tables, this one needs the
    id → table MAPPING so a consumer can resolve an entity reference to the
    physical name it must appear as in SQL.

    Only entries where the two genuinely differ are returned; an entity whose
    ``db_table_name`` still equals its id carries no information and is omitted,
    so a caller can treat "absent" as "nothing to resolve" without re-checking.
    """
    mapping: dict[str, str] = {}
    for raw in yamls or []:
        if not raw or not raw.strip():
            continue
        try:
            parsed = _load_yaml(raw)
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        entity_id = str(parsed.get("id") or "").strip()
        table = str(parsed.get("db_table_name") or "").strip()
        if entity_id and table and entity_id.lower() != table.lower():
            mapping[entity_id.lower()] = table
    return mapping


# ─────────────────────────────────────────────────────────────────────────────
# SQL parsing — regex-based, conservative on purpose
# ─────────────────────────────────────────────────────────────────────────────

# Matches tables after FROM / JOIN / INTO / UPDATE. Supports optional schema
# prefix ("public".name or schema.name) and optional quoting.
# Captures the bare table identifier.
_TABLE_REF = re.compile(
    r"""\b(?:FROM|JOIN|INTO|UPDATE)\s+
        (?:"[^"]+"\.|[A-Za-z_][A-Za-z0-9_]*\.)?   # optional schema.
        (?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))    # quoted OR bare identifier
    """,
    re.IGNORECASE | re.VERBOSE,
)

# CTE definitions: WITH <name> AS (...) / , <name> AS (...)
_CTE_DEF = re.compile(
    r"""(?:\bWITH\b|,)\s+
        (?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))
        \s+AS\s*\(
    """,
    re.IGNORECASE | re.VERBOSE,
)

# SQL keywords/functions we must not treat as tables even if the regex catches
# them (e.g. FROM (SELECT ... ) x → the "(" case is handled by regex structure,
# but belt-and-suspenders for common subquery-introducing tokens).
_SQL_NOISE = {
    "SELECT",
    "WHERE",
    "ON",
    "AS",
    "AND",
    "OR",
    "IN",
    "BY",
    "GROUP",
    "ORDER",
    "HAVING",
    "LIMIT",
    "UNION",
    "ALL",
    "DISTINCT",
}


def lowercase_physical_tables(sql: str, allowed_tables: set[str]) -> str:
    """Lowercase FROM/JOIN/INTO/UPDATE table identifiers that match a known
    physical table, leaving everything else (columns, aliases, the schema
    prefix segment) untouched.

    ``db_table_name`` is registered uppercase in the semantic layer (SAP HANA
    identifier folding convention — see :func:`build_allowed_tables`), and the
    LLM faithfully reproduces whatever casing the SCHEMA section shows it. On
    an Iceberg-backed catalog (e.g. Presto/Trino against watsonx.data) the
    physical tables are conventionally created lowercase, so the generated
    SQL never resolves without this fix-up. Deterministic post-generation
    correction rather than an LLM instruction — the "LLM as compiler"
    principle: don't rely on the model remembering to fold casing on its own.

    Reuses :data:`_TABLE_REF` (same conservative FROM/JOIN/INTO/UPDATE match as
    :func:`extract_referenced_tables`) so a table is only ever touched where it
    is unambiguously a table reference, never inside a column list or alias.
    """
    if not sql or not allowed_tables:
        return sql

    def _fix(m: re.Match[str]) -> str:
        quoted, bare = m.group(1), m.group(2)
        name = quoted if quoted is not None else bare
        if name.upper() not in allowed_tables:
            return m.group(0)
        group_idx = 1 if quoted is not None else 2
        full = m.group(0)
        start = m.start(group_idx) - m.start(0)
        end = m.end(group_idx) - m.start(0)
        return full[:start] + name.lower() + full[end:]

    return _TABLE_REF.sub(_fix, sql)


def extract_referenced_tables(sql: str) -> set[str]:
    """
    Extract the set of physical tables referenced in FROM/JOIN/INTO/UPDATE
    clauses, excluding CTE self-references. Returns identifiers uppercased
    to match HANA folding (case-insensitive comparison against allowed set).
    """
    if not sql:
        return set()

    cte_names: set[str] = set()
    for q, b in _CTE_DEF.findall(sql):
        name = q or b
        if name:
            cte_names.add(name.upper())

    refs: set[str] = set()
    for q, b in _TABLE_REF.findall(sql):
        name = q or b
        if not name:
            continue
        up = name.upper()
        if up in _SQL_NOISE:
            continue
        if up in cte_names:
            continue
        refs.add(up)
    return refs


# ─────────────────────────────────────────────────────────────────────────────
# Audit
# ─────────────────────────────────────────────────────────────────────────────


def audit_sql_scope(
    sql: str,
    allowed_tables: set[str],
) -> dict[str, Any]:
    """
    Compare tables referenced in `sql` against the authoritative
    `allowed_tables` set.

    Returns:
        {
          "ok":               bool,   # True iff no out-of-scope tables
          "referenced":       list,   # sorted upper-cased referenced tables
          "out_of_scope":     list,   # sorted upper-cased OOS tables
          "allowed":          list,   # sorted allowed set (for logging)
        }
    """
    referenced = extract_referenced_tables(sql)
    oos = sorted(t for t in referenced if t not in allowed_tables)
    return {
        "ok": not oos,
        "referenced": sorted(referenced),
        "out_of_scope": oos,
        "allowed": sorted(allowed_tables),
    }


def format_scope_feedback(
    audit: dict[str, Any],
    previous_sql: str,
) -> str:
    """
    Render a feedback block the LLM will see on retry. Lists the offending
    tables and the allowed set so the model can correct without guessing.
    """
    oos = audit.get("out_of_scope") or []
    allowed = audit.get("allowed") or []
    return (
        "RETRY — your previous SQL referenced physical tables that are NOT "
        "in the authoritative scope. Rewrite the query using ONLY the "
        "allowed tables.\n\n"
        f"Previous SQL (REJECTED):\n{previous_sql}\n\n"
        f"Out-of-scope tables you referenced: {', '.join(oos)}\n"
        f"Allowed tables (use ONLY these via their db_table_name in the "
        f"YAMLs): {', '.join(allowed)}\n\n"
        "Common cause: you pulled a bronze SAP table name from the "
        "`composed_of` or `source` lineage metadata inside a YAML. Those "
        "tables do NOT exist in the query database — only the Silver/Gold "
        "`db_table_name` does. Re-read the YAML_READING_RULES block and "
        "fix the FROM/JOIN clauses accordingly."
    )
