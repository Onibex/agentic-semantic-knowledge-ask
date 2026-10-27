# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""One repair attempt for a SQL statement the database rejected.

The SQL generators see neither the server's version nor the physical type a
column has in each environment, so a dialect limit or a type they do not know
surfaces only as an execution error. That error locates the problem, which a
prompt rule can only anticipate: ``repair_sql`` gives the model the failed
statement and the database's own error, once. A statement that fails twice
keeps its error.

The chat (``routers/query.py``) and the artifacts (``routers/artifact.py``)
both use it.
"""

from __future__ import annotations

import logging
import re

from .config import SettingsCache

logger = logging.getLogger(__name__)

# One-line dialect hint per engine, for the prompts that write or repair SQL
# outside the main generator. Covers every backend the DB registry supports, so
# no engine is silently told to emit PostgreSQL.
DIALECT_NOTES: dict[str, str] = {
    "hana": "SAP HANA SQL: double-quoted identifiers, ADD_DAYS() for dates, no NULLS LAST.",
    "postgresql": 'PostgreSQL: double-quoted identifiers, public."TABLE" format.',
    "snowflake": "Snowflake SQL: double-quoted identifiers, DATEADD() for dates.",
    "databricks": "Databricks/Spark SQL: backtick identifiers, date_add() for dates.",
    "bigquery": "BigQuery Standard SQL: backtick-quoted identifiers, DATE_ADD()/DATE_SUB().",
    # The two rules after the first sentence were measured on ClickHouse 22.1, where
    # both broke GONAC sub-queries: an alias shadows the column it is named after, so
    # SUM(x) AS x turns a later SUM(x) into SUM(SUM(x)) (ILLEGAL_AGGREGATION); and a
    # window result cannot be used inside another expression of the same SELECT, not
    # even through its alias (UNKNOWN_IDENTIFIER). The SQL each rule asks for is
    # valid on every version, so the note does not need to know the server's.
    "clickhouse": (
        "ClickHouse SQL: backtick identifiers, addDays() for dates. "
        "Never give an aggregate the alias of a column it reads: SUM(x) AS x breaks any later SUM(x). "
        "Compute ratios or arithmetic between window functions in an outer query, "
        "not in the SELECT that defines them."
    ),
    "sqlserver": "SQL Server T-SQL: [bracket] identifiers, DATEADD(), TOP n (no LIMIT).",
    "db2": "IBM Db2 SQL: double-quoted identifiers, FETCH FIRST n ROWS ONLY (no LIMIT).",
    "fabric": "Microsoft Fabric (T-SQL): [bracket] identifiers, DATEADD(), TOP n.",
}

# Errors whose text does not name their own fix. Measured on ClickHouse 22.1: told
# only "Unknown identifier: sum(x) OVER (...)", the model moved the aggregation into
# a subquery and kept the ratio between windows in the same SELECT, which fails the
# same way. With the hint the repair has the one change that works.
ERROR_HINTS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"Unknown identifier:.*\bOVER\s*\(", re.IGNORECASE | re.DOTALL),
        "This server cannot use a window function's result in another expression of the "
        "SELECT that defines it, not even through its alias. Compute the window columns in "
        "a subquery and do the arithmetic between them in the outer SELECT.",
    ),
    (
        re.compile(r"is found inside another aggregate function", re.IGNORECASE),
        "An alias that repeats a column name shadows that column: SUM(x) AS x makes every "
        "later SUM(x) a SUM(SUM(x)). Rename such aliases (x_total) and keep the rest.",
    ),
    # The three below are the GONAC chat's own failures on 22.1. The first error
    # quotes a UTF-8 lead byte, which says nothing about which name or why; the
    # other two name the types but not the conversion that reconciles them.
    (
        re.compile(r"Unrecognized token: '\\x[c-f][0-9a-f]'", re.IGNORECASE),
        "ClickHouse rejects letters outside ASCII (ñ, accented vowels) in a name that is not "
        "quoted. Spell every alias with ASCII letters, digits and underscores only (anio, not "
        "año) and keep the rest.",
    ),
    (
        re.compile(r"no supertype for types (String, Date|Date, String)", re.IGNORECASE),
        "A date stored as String is compared or joined with a Date. Wrap the String side in "
        "toDateOrNull(...), or toDateTimeOrNull(...) for a timestamp, so both sides share a type.",
    ),
    (
        re.compile(r"Illegal type Date(Time)? of first argument of function to\w*OrNull", re.IGNORECASE),
        "That column is already a Date: remove the conversion function around it and use the "
        "column as it is.",
    ),
]

# Failures no rewrite of the statement can fix: the server could not be reached,
# took too long, or refused the credentials. A repair would spend a model call and
# a second round trip to get the same error back.
_UNREPAIRABLE = re.compile(
    r"connection refused|connection reset|timed out|timeout|name or service not known|"
    r"failed to establish|max retries exceeded|authentication failed|password is incorrect|"
    r"no database is configured",
    re.IGNORECASE,
)


def strip_fences(text: str, lang: str) -> str:
    """The body of a ```lang (or bare ```) fenced block, else the text itself."""
    text = text.strip()
    if f"```{lang}" in text:
        return text.split(f"```{lang}")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text


def is_repairable(error: str | None) -> bool:
    """Whether rewriting the statement could plausibly fix ``error``."""
    return bool(error) and not _UNREPAIRABLE.search(error or "")


def repair_sql(failed_sql: str, error: str, db_type: str, *, phase: str) -> str | None:
    """Ask the LLM for ONE corrected version of a statement the database rejected.

    Where the error's text does not name the fix, ``ERROR_HINTS`` adds the
    explanation. ``phase`` names the call in the request's token breakdown.
    Returns ``None`` when no usable, different SQL comes back.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from ask_llm_gateway.application.factory import build_llm
    from ask_llm_gateway.infrastructure.token_tracker import track_phase

    dialect = DIALECT_NOTES.get(db_type, f"{db_type.upper()} SQL.")
    system = (
        f"You fix one {db_type.upper()} SQL statement that the database rejected. {dialect} "
        f"Keep the same tables, columns and analytical intent; change only what the error "
        f"requires. Return ONLY the corrected SQL statement, no markdown, no explanation."
    )
    user = f"SQL:\n{failed_sql}\n\nDatabase error:\n{error[:800]}"
    hints = [hint for pattern, hint in ERROR_HINTS if pattern.search(error)]
    if hints:
        user += "\n\nWhat the error means:\n" + "\n".join(f"- {h}" for h in hints)
    try:
        llm = build_llm(SettingsCache.get())
        with track_phase(phase):
            response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        fixed = strip_fences(response.content, "sql").rstrip(";").strip()
    except Exception as exc:
        logger.warning("SQL repair failed: %s", exc)
        return None
    if not fixed or fixed == failed_sql.strip().rstrip(";").strip():
        return None
    return fixed
