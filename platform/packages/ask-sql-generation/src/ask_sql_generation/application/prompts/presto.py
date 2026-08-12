"""Presto/Trino dialect rules (lite multi-DB).

Deltas vs HANA/PG: ANSI double-quote identifier quoting where UNQUOTED
identifiers fold to lower-case (quote to preserve exact casing), catalog.schema.table
three-level namespace (catalog is fixed per connection, so only the schema segment
is threaded through — same single-string convention as Databricks), no
STRING_AGG/LISTAGG (use array_join(array_agg())), current_date/date_add/date_diff
date functions, TRY_CAST for safe casts.
"""


def schema_prefix_rule(schema: str) -> str:
    return (
        f"PRESTO SCHEMA PREFIX (MANDATORY — overrides rule #2 below):\n"
        f'Qualify every table as "{schema}"."TABLE_NAME" (the catalog is fixed by '
        f"the connection — do not add a catalog segment).\n"
    )


STRICT_RULES = """STRICT PRESTO/TRINO SQL RULES:
1. Use ONLY tables and columns present in the SCHEMA section above — never invent names
2. Quote identifiers with double quotes "name". Presto folds UNQUOTED identifiers to
   lower-case, so ALWAYS quote to preserve the exact casing from the schema.
   Qualify tables as "schema"."table_name" (the catalog is implicit — never add a
   catalog segment to a table reference).
3. Identifiers are CASE-SENSITIVE once quoted — reproduce the EXACT casing from the schema.
4. Add LIMIT 500 by default to cap result size, UNLESS the user asks for aggregations/totals
   OR explicitly requests a specific number of rows (then use that exact count)
5. For monetary values, cast with CAST(value AS DECIMAL(18,2)) or TRY_CAST for safe casts.
6. Prefer readable snake_case aliases for all columns
7. String aggregation: use array_join(array_agg(expr), ', ') — there is no STRING_AGG/LISTAGG.
8. Dates: use current_date / current_timestamp. Arithmetic: date_add('day', n, d),
   date_diff('day', a, b), date_trunc('month', d).
9. SAP date/time columns may be stored as VARCHAR 'YYYY-MM-DD' with sentinels '' or
   '0000-00-00'. Normalize before comparing/sorting/joining:
   TRY_CAST(NULLIF(NULLIF(col, ''), '0000-00-00') AS DATE).
10. Keep to plain INNER/LEFT JOIN and explicit GROUP BY (list every non-aggregated selected column).
11. Table aliases MUST NOT be SQL reserved words — use a safe short alias (t1, inv, sit).
"""

ROLE_LINE = (
    "You are a Presto/Trino SQL expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
