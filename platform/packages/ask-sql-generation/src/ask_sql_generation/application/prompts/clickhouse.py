"""ClickHouse dialect rules (lite multi-DB, 2026-07).

Deltas vs HANA/PG: identifiers are CASE-SENSITIVE (emit exact casing — do NOT
uppercase), two-level database.table namespace, no STRING_AGG (use
arrayStringConcat(groupArray())), today()/now()/addDays date functions,
Decimal(P,S) numeric casts, and NO FINAL modifier in generated SQL — plain
MergeTree tables reject it (ILLEGAL_FINAL). Query-time dedup for
ReplacingMergeTree CDC deployments is the connection's opt-in ``final=1``
setting (see ask-sql-executor's clickhouse_adapter, which the server applies
only to engines that support it); the SQL itself guarantees uniqueness through
the queried key with standard GROUP BY / DISTINCT, portable to any engine.
"""


def schema_prefix_rule(schema: str) -> str:
    return (
        f"CLICKHOUSE DATABASE PREFIX (MANDATORY — overrides rule #2 below):\n"
        f'Qualify every table with the database: "{schema}"."table_name"\n'
        f"(ClickHouse's 'database' is the schema; there is no separate catalog.)\n"
    )


STRICT_RULES = """STRICT CLICKHOUSE SQL RULES:
1. Use ONLY tables and columns present in the SCHEMA section above — never invent names
2. Quote identifiers with double quotes "name" (do NOT use backticks in generated SQL).
   ClickHouse namespace is database.table — qualify as "database"."table" when a prefix block is present.
3. Identifiers are CASE-SENSITIVE — reproduce the EXACT casing from the schema; never upper/lower-case names.
4. CRITICAL — DEDUPLICATION: NEVER write the FINAL modifier — plain MergeTree tables reject it
   ("Storage MergeTree doesn't support FINAL"); when a deployment needs read-time dedup it is
   applied at the CONNECTION level, never in SQL. Instead, guarantee uniqueness through the key
   being queried, as in any SQL database:
     - Aggregations: GROUP BY every selected non-aggregated column (see rule 11).
     - Row/detail listings where the same business key could repeat: SELECT DISTINCT, or GROUP BY
       the identifying key columns, so each key appears exactly once.
     WRONG: FROM "db"."SALES" AS t FINAL      (FINAL is forbidden in generated SQL)
5. Add LIMIT 500 by default to cap result size, UNLESS the user asks for aggregations/totals
   OR explicitly requests a specific number of rows (then use that exact count)
6. For monetary values, cast with toDecimal64(value, 2) or CAST(value AS Decimal(18,2)).
7. Prefer readable snake_case aliases for all columns
8. String aggregation: use arrayStringConcat(groupArray(expr), ', ') — there is no STRING_AGG/LISTAGG.
9. Dates: use today() / now(). Arithmetic: addDays(d, n), subtractDays(d, n), dateDiff('day', a, b),
   toStartOfMonth(d). (CURRENT_DATE also works but today()/now() are idiomatic.)
10. DATE TYPES — ClickHouse will NOT implicitly join/compare across types. A SAP date column may be a
    String 'YYYY-MM-DD' (sentinels '' / '0000-00-00') while the other side is a native Date/DateTime;
    joining/comparing them raises error 53 "Can't infer common type ... Date vs String". Whenever you
    JOIN or compare a STRING date to a Date/DateTime (or vice versa), cast the STRING side with
    toDateOrNull(...) so BOTH sides share a type (toDateOrNull also maps '' / '0000-00-00' to NULL):
      JOIN:  ON inv."future_date" = toDateOrNull(rec."date_reception")
      WHERE: WHERE toDateOrNull("date_reception") >= today() - 30
      SORT:  ORDER BY toDateOrNull("date_reception") DESC
    (For a lone String timestamp use toDateTimeOrNull(...) / parseDateTimeBestEffortOrNull(...).)
11. Keep to plain INNER/LEFT JOIN and explicit GROUP BY (list every non-aggregated selected column).
12. Table aliases MUST NOT be SQL reserved words — use a safe short alias (t1, inv, sit).
"""

ROLE_LINE = (
    "You are a ClickHouse SQL expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
