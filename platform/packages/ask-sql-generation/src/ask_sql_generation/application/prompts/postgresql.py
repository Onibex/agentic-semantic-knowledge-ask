"""PostgreSQL-specific dialect rules — verbatim from the legacy freeform generator."""

# PATCH (2026-06-17, refined 2026-07-15) — compensates for an OPEN GAP in
# docs/semantic-layer/SILVER_LAYER.md §6.2 (temporal fields, not yet ratified).
# SAP dates land in Silver as VARCHAR 'YYYY-MM-DD'
# but Gold uses native DATE/TIMESTAMP, and the declared `type` can't be trusted.
# Rule 9 forces a normalization so date comparisons work for BOTH representations.
# The column is cast to ::text FIRST (2026-07-15 fix): NULLIF(col, '') on a NATIVE
# date/timestamp column makes Postgres coerce '' to date at parse time and raises
# "invalid input syntax for type date: \"\"". col::text sidesteps that — a real
# date renders as 'YYYY-MM-DD' text, a VARCHAR passes through unchanged, and the
# empty/sentinel guard then applies to text in both cases. Stopgap — relax once
# SAP dates are normalized to native DATE at the Silver boundary. Tracked in the
# internal backlog.
STRICT_RULES = """STRICT POSTGRESQL RULES:
1. Use ONLY tables and columns present in the SCHEMA section above — never invent names
2. Table names MUST be: public."EXACT_TABLE_NAME" (double quotes, exact casing)
3. Column names MUST be wrapped in double quotes with exact casing: "COLUMN_NAME"
4. Add LIMIT 500 by default to cap result size, UNLESS the user asks for aggregations/totals
   OR explicitly requests a specific number of rows (then use that exact count)
5. For monetary values, use ROUND(value::numeric, 2)
6. Prefer readable snake_case aliases for all columns
7. Table aliases MUST NOT be SQL reserved words — NEVER alias a table as
   is, as, in, on, or, and, to, do, at, by. Use a safe short alias (inv, sit,
   t1, t2) or a descriptive snake_case alias. Example: write
   JOIN public."GOLD_INVENTORY_SITUATION" sit  (NOT ... is)
8. Apply ALL rules from the PG_SAP_RULES section above
9. SAP date/time columns may be stored as VARCHAR 'YYYY-MM-DD' (Silver) OR as native
   DATE/TIMESTAMP (Gold) — the declared column type is NOT reliable, and text dates may
   contain the SAP sentinels '' (empty) or '0000-00-00'. To filter, compare, or sort ANY
   date column, normalize it FIRST with CAST(NULLIF(NULLIF(col::text, ''), '0000-00-00') AS DATE).
   The ::text cast is MANDATORY and must come BEFORE the NULLIFs: without it, NULLIF(col, '')
   on a NATIVE date/timestamp column raises "invalid input syntax for type date: ''" (Postgres
   coerces '' to date). ::text makes a real date render as 'YYYY-MM-DD' and a VARCHAR pass
   through, so the guard is safe for BOTH. NEVER call EXTRACT()/DATE_TRUNC() on, or compare to
   CURRENT_DATE, a raw date column. Examples:
     Current month: WHERE CAST(NULLIF(NULLIF(t."erdat_vbak"::text, ''), '0000-00-00') AS DATE) >= DATE_TRUNC('month', CURRENT_DATE)::date
                      AND CAST(NULLIF(NULLIF(t."erdat_vbak"::text, ''), '0000-00-00') AS DATE) <  (DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month')::date
     Filter year:   EXTRACT(YEAR FROM CAST(NULLIF(NULLIF("field"::text, ''), '0000-00-00') AS DATE)) = 2025
     ORDER BY date: ORDER BY CAST(NULLIF(NULLIF("field"::text, ''), '0000-00-00') AS DATE) DESC NULLS LAST
     DATE_TRUNC SELECT/GROUP BY: DATE_TRUNC('month', CAST(NULLIF(NULLIF("delivery_date"::text, ''), '0000-00-00') AS DATE))
                 — ALWAYS wrap date columns with CAST(NULLIF(NULLIF(col::text, ...) when used inside DATE_TRUNC, EXTRACT, or any date function
"""

ROLE_LINE = (
    "You are a PostgreSQL expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
