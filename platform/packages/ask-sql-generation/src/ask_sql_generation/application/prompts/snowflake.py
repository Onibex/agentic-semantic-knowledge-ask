# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Snowflake dialect rules (lite multi-DB, 2026-07).

Snowflake is PG-adjacent: LIMIT, double-quote quoting, UPPERCASE folding of
unquoted identifiers (matches our scope_validator). Deltas vs HANA/PG:
LISTAGG (not STRING_AGG), DATEADD/DATEDIFF, three-part DATABASE.SCHEMA.TABLE,
NUMBER(38,2) decimals.
"""


def schema_prefix_rule(schema: str) -> str:
    return (
        f"SNOWFLAKE SCHEMA PREFIX (MANDATORY — overrides rule #2 below):\n"
        f'Qualify every table: "{schema}"."TABLE_NAME"\n'
        f'Example: FROM "{schema}"."SILVER_SD_SALES_ORDER" AS t\n'
        f'NEVER write a bare table name without the "{schema}". prefix.\n'
    )


STRICT_RULES = """STRICT SNOWFLAKE SQL RULES:
1. Use ONLY tables and columns present in the SCHEMA section above — never invent names
2. Table names MUST use double quotes with the EXACT casing shown in the SCHEMA section.
   When a SNOWFLAKE SCHEMA PREFIX block is present above, ALWAYS qualify: "SCHEMA"."TABLE_NAME"
3. CRITICAL — Column names MUST be double-quoted with the EXACT casing shown in the SCHEMA
   section (the curated columns are LOWERCASE, e.g. "vbeln_vbak", "audat_vbak"). An UNQUOTED
   identifier is folded to UPPERCASE by Snowflake and fails as `invalid identifier`.
   Quote EVERY column reference — SELECT list, JOIN ... ON, WHERE, GROUP BY, ORDER BY.
     CORRECT: SELECT t1."vbeln_vbak" ... ON t1."matnr_vbap" = t2."matnr_mara" WHERE t1."audat_vbak" >= ...
     WRONG:   SELECT t1.vbeln_vbak ...  (folds to T1.VBELN_VBAK -> invalid identifier)
4. Add LIMIT 500 by default to cap result size, UNLESS the user asks for aggregations/totals
   OR explicitly requests a specific number of rows (then use that exact count)
5. For monetary values, use ROUND(value, 2) (decimals are NUMBER(38,2); cast with CAST(x AS NUMBER(38,2)))
6. Prefer readable snake_case aliases for all columns
7. String aggregation: use LISTAGG(expr, ', ') WITHIN GROUP (ORDER BY expr) — NOT STRING_AGG / LIST_AGG.
8. Dates: use CURRENT_DATE / CURRENT_TIMESTAMP. Date arithmetic uses DATEADD(unit, n, date) and
   DATEDIFF(unit, start, end): yesterday = DATEADD(day, -1, CURRENT_DATE); 7 days ago = DATEADD(day, -7, CURRENT_DATE).
9. SAP date/time columns may be stored as VARCHAR 'YYYY-MM-DD' with sentinels '' or '0000-00-00'.
   Normalize before comparing/sorting: TRY_TO_DATE(NULLIF(NULLIF(col, ''), '0000-00-00')).
10. Window functions (ROW_NUMBER, RANK, LAG, LEAD) must be in a subquery — cannot be used in WHERE/HAVING directly.
11. Table aliases MUST NOT be SQL reserved words — use a safe short alias (t1, inv, sit).
"""

ROLE_LINE = (
    "You are a Snowflake SQL expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
