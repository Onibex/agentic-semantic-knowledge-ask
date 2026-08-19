# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Databricks (Spark SQL) dialect rules (lite multi-DB, 2026-07).

Deltas vs HANA/PG: backtick identifier quoting (double quotes are string
literals), lowercase/case-insensitive identifiers, Unity Catalog three-level
catalog.schema.table, concat_ws(collect_list()) for string aggregation,
date_add/datediff/current_date() date functions.
"""


def schema_prefix_rule(schema: str) -> str:
    return (
        f"DATABRICKS SCHEMA PREFIX (MANDATORY — overrides rule #2 below):\n"
        f"Qualify every table as SCHEMA then TABLE, EACH segment in its OWN backticks with the "
        f"dot OUTSIDE the backticks:\n"
        f"  CORRECT: FROM `{schema}`.`TABLE_NAME` AS t\n"
        f"  WRONG:   FROM `{schema}.TABLE_NAME`   (one identifier with a literal dot — table not found)\n"
    )


STRICT_RULES = """STRICT DATABRICKS (Spark SQL) RULES:
1. Use ONLY tables and columns present in the SCHEMA section above — never invent names
2. Identifiers use BACKTICKS (double quotes are string literals in Databricks). CRITICAL:
   EACH name segment gets its OWN pair of backticks and every dot goes OUTSIDE the backticks —
   NEVER put a dot inside a backtick pair. Qualify as `catalog`.`schema`.`table` (or `schema`.`table`).
   CORRECT: FROM `business_dp`.`GOLD_INVENTORY_SITUATION`
   WRONG:   FROM `business_dp.GOLD_INVENTORY_SITUATION`  (ONE identifier with a literal dot — table not found)
3. Column names should be referenced with backticks when they need quoting: `column_name`
4. Add LIMIT 500 by default to cap result size, UNLESS the user asks for aggregations/totals
   OR explicitly requests a specific number of rows (then use that exact count)
5. For monetary values, use ROUND(CAST(value AS DECIMAL(18,2)), 2)
6. Prefer readable snake_case aliases for all columns
7. String aggregation: use concat_ws(', ', collect_list(expr)) — LISTAGG/STRING_AGG may not exist on older runtimes.
8. Dates: use current_date() / current_timestamp(). Arithmetic: date_add(col, n), date_sub(col, n),
   datediff(end, start), add_months(col, n), date_trunc('MONTH', col).
9. SAP date/time columns may be stored as STRING 'YYYY-MM-DD' with sentinels '' or '0000-00-00'.
   Normalize before comparing/sorting: to_date(nullif(nullif(col, ''), '0000-00-00')).
10. Window functions must be in a subquery — cannot be used in WHERE/HAVING directly.
11. Table aliases MUST NOT be SQL reserved words — use a safe short alias (t1, inv, sit).
"""

ROLE_LINE = (
    "You are a Databricks (Spark SQL) expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
