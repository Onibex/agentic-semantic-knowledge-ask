# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""IBM Db2 dialect rules (lite multi-DB, 2026-07).

Db2 is HANA-like: double-quote quoting, UPPERCASE folding of unquoted
identifiers (matches our scope_validator), schema.table qualification. Deltas:
FETCH FIRST n ROWS ONLY (not LIMIT), LISTAGG(...) WITHIN GROUP, CURRENT DATE
special register + labeled-duration date math.
"""


def schema_prefix_rule(schema: str) -> str:
    return (
        f"DB2 SCHEMA PREFIX (MANDATORY — overrides rule #2 below):\n"
        f'Qualify every table: "{schema}"."TABLE_NAME"\n'
        f'Example: FROM "{schema}"."SILVER_SD_SALES_ORDER" AS t\n'
    )


STRICT_RULES = """STRICT IBM Db2 SQL RULES:
1. Use ONLY tables and columns present in the SCHEMA section above — never invent names
2. Table names MUST use double quotes with exact casing: "EXACT_TABLE_NAME"
   When a DB2 SCHEMA PREFIX block is present above, ALWAYS qualify: "SCHEMA"."TABLE_NAME"
3. CRITICAL — Column names MUST be double-quoted with the EXACT casing shown in the SCHEMA
   section (the curated columns are LOWERCASE, e.g. "vbeln_vbak", "matnr_vbap"). An UNQUOTED
   identifier is folded to UPPERCASE by Db2 and fails as `SQL0206N ... is not valid` (SQLCODE -206).
   Quote EVERY column reference — SELECT list, JOIN ... ON, WHERE, GROUP BY, ORDER BY.
     CORRECT: SELECT t1."vbeln_vbak" ... ON t1."matnr_vbap" = t2."matnr_mara" ... FETCH FIRST 500 ROWS ONLY
     WRONG:   SELECT t1.vbeln_vbak ... ON t1.matnr_vbap = t2.matnr_mara  (folds to T1.MATNR_VBAP -> SQL0206N)
4. There is NO LIMIT in Db2. Cap rows with ... FETCH FIRST 500 ROWS ONLY by default, UNLESS the user asks
   for aggregations/totals OR a specific number (then FETCH FIRST n ROWS ONLY). Paging: OFFSET n ROWS FETCH FIRST n ROWS ONLY.
5. For monetary values, use CAST(value AS DECIMAL(18,2)).
6. Prefer readable snake_case aliases for all columns
7. String aggregation: use LISTAGG(expr, ', ') WITHIN GROUP (ORDER BY expr) — NOT STRING_AGG.
8. Dates: use the CURRENT DATE special register (two words). Arithmetic uses labeled durations:
   yesterday = CURRENT DATE - 1 DAY; 7 days ago = CURRENT DATE - 7 DAYS; next month = CURRENT DATE + 1 MONTH.
9. Booleans: prefer 0/1 comparisons on SMALLINT flags (native BOOLEAN only exists on Db2 11.1+).
10. SAP date/time columns may be stored as VARCHAR 'YYYY-MM-DD' with sentinels '' or '0000-00-00'.
    Normalize before comparing/sorting: DATE(NULLIF(NULLIF(col, ''), '0000-00-00')).
11. Window functions (ROW_NUMBER, RANK, LAG, LEAD) must be in a subquery — cannot be used in WHERE/HAVING directly.
12. Table aliases MUST NOT be SQL reserved words — use a safe short alias (t1, inv, sit).
"""

ROLE_LINE = (
    "You are an IBM Db2 SQL expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
