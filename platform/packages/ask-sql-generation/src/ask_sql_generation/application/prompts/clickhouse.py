# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""ClickHouse dialect rules (lite multi-DB, 2026-07).

Deltas vs HANA/PG: identifiers are CASE-SENSITIVE (emit exact casing — do NOT
uppercase), two-level database.table namespace, no STRING_AGG (use
arrayStringConcat(groupArray())), today()/now()/addDays date functions,
Decimal(P,S) numeric casts, and no FINAL modifier (rule 13).

Deduplication and FINAL are INDEPENDENT concerns and the rules keep them apart:

  * Deduplication (rule 4) is SQL semantics. Uniqueness follows from the key the
    QUESTION asks about, expressed with standard GROUP BY / DISTINCT — the same
    reasoning in every SQL dialect, with no knowledge of the storage engine.
  * FINAL (rule 13) is a ClickHouse engine mechanism (merge-on-read for the
    collapsing MergeTree variants). It is a deployment property, applied through
    the connection's opt-in ``final=1`` setting in ask-sql-executor's
    clickhouse_adapter, and it never appears in generated SQL.

Treating FINAL as "how you deduplicate" is what made every query fail against a
plain MergeTree table; the two axes must not be coupled again.
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
4. DEDUPLICATION — guarantee uniqueness through the key the QUESTION asks about, exactly as in
   any SQL database. This is a property of the query, NOT of the storage engine — never reason
   about engines here:
     - Aggregations: GROUP BY every selected non-aggregated column (see rule 11).
     - Row/detail listings where the same business key could repeat: SELECT DISTINCT, or GROUP BY
       the identifying key columns, so each key appears exactly once.
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
13. NEVER write the FINAL modifier. It is an engine-level merge-on-read mechanism owned by the
    DEPLOYMENT (enabled per connection), unrelated to how a query deduplicates (rule 4), and plain
    MergeTree tables reject it outright: "Storage MergeTree doesn't support FINAL".
      WRONG: FROM "db"."SALES" AS t FINAL
"""

ROLE_LINE = (
    "You are a ClickHouse SQL expert working with SAP data products "
    "exposed as a curated semantic layer (YAMLs)."
)
