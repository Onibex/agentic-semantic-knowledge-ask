# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Microsoft SQL Server (T-SQL) dialect rules (lite multi-DB, 2026-07).

Deltas vs HANA/PG: NO LIMIT — use TOP (n) or OFFSET/FETCH; default schema dbo;
GETDATE()/DATEADD/DATEDIFF date functions (no INTERVAL); + / CONCAT (not ||);
BIT not BOOLEAN. We instruct double-quote identifiers (QUOTED_IDENTIFIER is ON
under ODBC) so the scope validator's parser keeps working — not [brackets].
"""


def schema_prefix_rule(schema: str) -> str:
    return (
        f"SQL SERVER SCHEMA PREFIX (MANDATORY — overrides rule #2 below):\n"
        f'Qualify every table: "{schema}"."TABLE_NAME"\n'
        f'(Default schema is dbo when none is configured: dbo."TABLE_NAME".)\n'
    )


STRICT_RULES = """STRICT SQL SERVER (T-SQL) RULES:
1. Use ONLY tables and columns present in the SCHEMA section above — never invent names
2. Table names MUST be qualified with a schema and double-quoted: "SCHEMA"."TABLE_NAME"
   (default schema is dbo). Do NOT use [bracket] quoting — use "double quotes".
3. Column names MUST be wrapped in double quotes with exact casing: "COLUMN_NAME"
4. There is NO LIMIT in T-SQL. Cap rows with SELECT TOP (500) ... by default, UNLESS the user asks
   for aggregations/totals OR a specific number (then TOP (n)). For paging use ORDER BY ... OFFSET 0 ROWS
   FETCH NEXT n ROWS ONLY.
5. For monetary values, use CAST(value AS DECIMAL(18,2)) (or CONVERT(DECIMAL(18,2), value)).
6. Prefer readable snake_case aliases for all columns
7. String aggregation: use STRING_AGG(expr, ', ') WITHIN GROUP (ORDER BY expr) (SQL Server 2017+).
8. Dates: use GETDATE() / SYSDATETIME(); today = CAST(GETDATE() AS DATE). Arithmetic: DATEADD(day, -7, GETDATE()),
   DATEDIFF(day, a, b). There is NO INTERVAL arithmetic and (pre-2025) NO CURRENT_DATE.
9. String concatenation uses + or CONCAT(...), NEVER ||. Booleans use BIT (1/0), not TRUE/FALSE.
10. SAP date/time columns may be stored as VARCHAR 'YYYY-MM-DD' with sentinels '' or '0000-00-00'.
    Normalize before comparing/sorting: TRY_CAST(NULLIF(NULLIF(col, ''), '0000-00-00') AS DATE).
11. Window functions (ROW_NUMBER, RANK, LAG, LEAD) must be in a subquery — cannot be used in WHERE/HAVING directly.
12. Table aliases MUST NOT be SQL reserved words — use a safe short alias (t1, inv, sit).
"""

ROLE_LINE = (
    "You are a Microsoft SQL Server (T-SQL) expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
