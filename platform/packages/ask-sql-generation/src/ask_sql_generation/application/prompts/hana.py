"""HANA-specific dialect rules — verbatim from the legacy freeform generator.

Edits here change the SQL the LLM produces. Re-validate against the
10-question benchmark before merging.
"""


def schema_prefix_rule(schema: str) -> str:
    """Returns a mandatory schema-prefix block to prepend to STRICT_RULES when a schema is configured."""
    return (
        f"HANA SCHEMA PREFIX (MANDATORY — this overrides rule #2 below):\n"
        f'Every table reference MUST be qualified: "{schema}"."TABLE_NAME"\n'
        f'Example: FROM "{schema}"."SILVER_SD_SALES_ORDER" AS t\n'
        f'NEVER write a bare table name without the "{schema}". prefix.\n'
    )


# PATCH (2026-06-17) — compensates for an OPEN GAP in docs/semantic-layer/
# SILVER_LAYER.md §6.2 (temporal fields, not yet ratified).
# SAP dates land in Silver as VARCHAR/NVARCHAR 'YYYY-MM-DD' but Gold uses native
# DATE/TIMESTAMP, and the declared `type` can't be trusted. Rule 17 below forces a CAST
# so date comparisons work for BOTH representations. This is a stopgap — relax/remove it
# once SAP dates are normalized to native DATE at the Silver boundary (see the standard's
# proposed end-state). Tracked in the internal backlog.
STRICT_RULES = """STRICT SAP HANA SQL RULES:
1. Use ONLY tables and columns present in the SCHEMA section above — never invent names
2. Table names MUST use double quotes with exact casing: "EXACT_TABLE_NAME"
   When a HANA SCHEMA PREFIX block is present above, ALWAYS qualify every table: "SCHEMA"."TABLE_NAME"
3. Column names MUST be wrapped in double quotes with exact casing: "COLUMN_NAME"
4. Add LIMIT 500 by default to cap result size, UNLESS the user asks for aggregations/totals
   OR explicitly requests a specific number of rows (then use that exact count)
5. For monetary values, use ROUND(value, 2)
6. Prefer readable snake_case aliases for all columns
7. NEVER use SELECT aliases or CTE column names in HAVING or WHERE — HANA does not support this.
   WRONG:  GROUP BY x HAVING total_sales > 0
   CORRECT: Wrap in a subquery and filter with WHERE in the outer query:
   SELECT * FROM ( ... your aggregation ... ) t WHERE t.total_sales > 0
8. NEVER filter on computed/aggregated columns with HAVING if those columns come from a CTE alias.
   Always use a wrapping subquery + WHERE instead.
9. Window functions (ROW_NUMBER, RANK, LAG, LEAD) MUST be in a subquery — cannot be used in WHERE/HAVING directly.
   Always wrap: SELECT * FROM ( SELECT ..., ROW_NUMBER() OVER (...) AS rn FROM ... ) t WHERE t.rn = 1
10. LIST_AGG is not available in SAP HANA Cloud — use STRING_AGG(column, separator) instead.
    NEVER use STRING_AGG(DISTINCT ...) — HANA does not support DISTINCT inside STRING_AGG.
    To deduplicate, use a CTE/subquery with SELECT DISTINCT, then STRING_AGG the already-distinct values.
11. MONTH(date) and YEAR(date) functions are valid in HANA.
12. Use CURRENT_DATE for today's date (not NOW(), GETDATE(), or SYSDATE).
    NEVER use arithmetic on dates: CURRENT_DATE - 1 is INVALID in HANA.
    Always use ADD_DAYS() for date arithmetic:
      Yesterday:        ADD_DAYS(CURRENT_DATE, -1)
      7 days ago:       ADD_DAYS(CURRENT_DATE, -7)
      Next week:        ADD_DAYS(CURRENT_DATE, 7)
      First of month:   ADD_DAYS(CURRENT_DATE, -(DAY(CURRENT_DATE) - 1))
13. ORDER BY can reference SELECT aliases in HANA — this is allowed.
    But HAVING and WHERE MUST use the actual expressions, not aliases.
    CRITICAL for UNION ALL: ORDER BY can ONLY reference columns present in the
    final output column list of every branch. NULLS LAST / NULLS FIRST are NOT
    supported in SAP HANA ORDER BY — remove them entirely.
14. CRITICAL — Column name casing in CTEs and subqueries in HANA:
    HANA is strict about identifier casing. Follow these rules exactly:

    a) When selecting a physical table column with double quotes (e.g. "plant_id"),
       the CTE output column retains the exact lowercase name. You MUST reference
       it with double quotes in outer CTEs:
         CORRECT: inv."plant_id"
         WRONG:   inv.plant_id   ← HANA folds to INV.PLANT_ID, not found

    b) When defining a computed alias WITHOUT double quotes (e.g. SUM(...) AS total_qty),
       HANA stores it as UPPERCASE. Reference it WITHOUT double quotes:
         CORRECT: inv.total_qty  (HANA resolves to TOTAL_QTY internally)
         WRONG:   inv."total_qty"

    c) SAFEST approach: always double-quote every alias in CTE definitions:
         SELECT "plant_id" AS "plant_id", SUM("on_hand") AS "on_hand" ...
       Then reference ALL CTE columns with double quotes.

15. Prefer CTEs (WITH clause) over inline subqueries. Always use approach 14c:
    double-quote every alias in CTE SELECT lists, and reference them with double quotes.
16. Table aliases MUST NOT be SQL reserved words — NEVER alias a table as
    is, as, in, on, or, and, to, do, at, by. Use a safe short alias (inv, sit,
    t1, t2) or a descriptive name. Example: JOIN ... AS sit  (NOT ... AS is)
17. SAP date/time columns may be stored as VARCHAR/NVARCHAR 'YYYY-MM-DD' (Silver) OR as
    native DATE/TIMESTAMP (Gold) — the declared column type is NOT reliable, and text dates
    may contain the SAP sentinels '' (empty) or '0000-00-00'. To filter, compare, or sort ANY
    date column, normalize it FIRST with CAST(NULLIF(NULLIF(col, ''), '0000-00-00') AS DATE).
    NEVER compare a raw date column to CURRENT_DATE (type-mismatch error). Combine with the
    ADD_DAYS arithmetic in rule 12 — e.g. current month:
      WHERE CAST(NULLIF(NULLIF(t."erdat_vbak", ''), '0000-00-00') AS DATE) >= ADD_DAYS(CURRENT_DATE, -(DAY(CURRENT_DATE) - 1))
"""

ROLE_LINE = (
    "You are a SAP HANA SQL expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
