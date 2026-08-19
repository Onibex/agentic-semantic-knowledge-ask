# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Google BigQuery (GoogleSQL) dialect rules (lite multi-DB, 2026-07).

Deltas vs HANA/PG: backtick identifier quoting (double quotes are string
literals), three-part `project.dataset.table` names, case-SENSITIVE
dataset/table names, function-style date math (CURRENT_DATE(), DATE_SUB(...,
INTERVAL n DAY)), NUMERIC decimals, SAFE_CAST. Note: LIMIT does NOT reduce
bytes billed — push partition/cluster filters.
"""


def schema_prefix_rule(schema: str) -> str:
    return (
        f"BIGQUERY DATASET PREFIX (MANDATORY — overrides rule #2 below):\n"
        f"Qualify every table with the dataset in backticks: `{schema}.TABLE_NAME`\n"
        f"(If a project is required use `project.{schema}.TABLE_NAME`.)\n"
    )


STRICT_RULES = """STRICT BIGQUERY (GoogleSQL) RULES:
1. Use ONLY tables and columns present in the SCHEMA section above — never invent names
2. Identifiers are quoted with BACKTICKS `name` (double quotes are STRING LITERALS in BigQuery).
   Qualify tables as `dataset.TABLE_NAME` (or `project.dataset.TABLE_NAME`).
3. Dataset and table names are CASE-SENSITIVE — reproduce the EXACT casing from the schema.
4. Add LIMIT 500 by default to cap displayed rows, UNLESS the user asks for aggregations/totals
   OR a specific number. NOTE: LIMIT does NOT reduce bytes scanned/billed — always add partition/date
   filters in WHERE to bound cost.
5. For monetary values, use ROUND(value, 2); exact decimals are NUMERIC — cast with CAST(x AS NUMERIC)
   or SAFE_CAST(x AS NUMERIC) to avoid aborting the whole query on a bad row.
6. Prefer readable snake_case aliases for all columns
7. String aggregation: use STRING_AGG(expr, ', ') or ARRAY_AGG.
8. Dates: use CURRENT_DATE() (with parentheses). Arithmetic: DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY),
   DATE_ADD(...), DATE_DIFF(d1, d2, DAY), DATE_TRUNC(d, MONTH), EXTRACT(YEAR FROM d).
9. SAP date/time columns may be stored as STRING 'YYYY-MM-DD' with sentinels '' or '0000-00-00'.
   Normalize before comparing/sorting: SAFE.PARSE_DATE('%Y-%m-%d', NULLIF(NULLIF(col, ''), '0000-00-00')).
10. Window functions (ROW_NUMBER, RANK, LAG, LEAD) must be in a subquery — cannot be used in WHERE/HAVING directly.
11. Table aliases MUST NOT be SQL reserved words — use a safe short alias (t1, inv, sit).
"""

ROLE_LINE = (
    "You are a Google BigQuery (GoogleSQL) expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
