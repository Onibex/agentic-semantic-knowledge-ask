# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask_intent_resolution.flash.infrastructure.sql_service — chunk-RAG SQL
generation for the Flash strategy.

Iter N: absorbed from packages/ask-flash-rag (Iter 8.9). The
SCHEMA_PROMPT_TEMPLATE / DOC_PROMPT_TEMPLATE constants and the execute /
format / no_results / silver-layer helpers were removed in the same pass —
the orchestrator handles SCHEMA/DOCS through ask-schema-service /
ask-docs-service, and SQL execution + formatting now go through
ask-sql-executor.SqlExecutorService.
"""

import json

from langchain_core.messages import HumanMessage

from ask_llm_gateway.infrastructure.response_utils import content_to_text

# Flash RAG scaffold reused for the new lite multi-DB backends. The dialect
# rules themselves come from the single source of truth in ask_sql_generation
# (see _shared_dialect), so Flash does not re-maintain a per-dialect prompt.
# NOTE: this module fills the {question}/{schema_context}/{business_context}
# placeholders via str.replace (NOT str.format), so literal JSON braces in the
# RESPONSE FORMAT block must be SINGLE ({ }). Doubled braces ({{ }}) would be
# sent verbatim and echoed by the model, breaking json.loads.
_FLASH_SCAFFOLD = """USER QUESTION:
{question}

AVAILABLE SCHEMA INFORMATION (from RAG registry):
{schema_context}

{business_context}

"""

_FLASH_RESPONSE_FORMAT = """

RESPONSE FORMAT (JSON only, no markdown):
{
    "table_name": "exact table name from schema",
    "sql": "SELECT ...",
    "explanation": "brief reasoning for table and approach",
    "grain": "transactional|aggregated",
    "is_dashboard_ready": true|false,
    "rules_applied": ["list of key rules applied"]
}
"""


def _shared_dialect(db_type: str) -> tuple[str, str]:
    """Return (role_line, strict_rules) for a new backend from the shared
    ask_sql_generation dialect registry. Raises on an unknown/unavailable
    dialect (A0 — never silently emit the wrong dialect's SQL)."""
    try:
        from ask_sql_generation.application.prompts.registry import (
            get_dialect,
            supported_dialects,
        )
    except Exception as exc:  # pragma: no cover - packaging edge
        raise ValueError(
            f"Flash SQL generation for db_type={db_type!r} needs ask_sql_generation "
            f"dialect prompts, which are unavailable: {exc}"
        ) from exc
    dialect = get_dialect(db_type)
    if dialect is None:
        raise ValueError(
            f"Flash SQL generation: unsupported db_type={db_type!r}. "
            f"Supported: {supported_dialects()}"
        )
    return dialect.role_line, dialect.strict_rules


def _build_sql_prompt(db_type: str) -> str:
    if db_type == "hana":
        return (
            "You are a SAP HANA SQL expert working with SAP data products.\n"
            + """USER QUESTION:
{question}

AVAILABLE SCHEMA INFORMATION (from RAG registry):
{schema_context}

{business_context}

STRICT SAP HANA SQL RULES:
1. Use ONLY tables and columns explicitly listed in the AVAILABLE SCHEMA INFORMATION above.
   NEVER fabricate a table or column name that does not appear in the schema context.
   If the schema context does not mention a table you think should exist, use the closest
   matching table that IS listed — or return an error explaining what is missing.
   WRONG: FROM schema."GOLD_MM_INVENTORY_POSITION"  ← invented, not in schema
   CORRECT: FROM schema."GOLD_INVENTORY_SITUATION"  ← exactly as listed in schema
2. Table names MUST use double quotes with exact casing: "EXACT_TABLE_NAME"
   When a HANA SCHEMA PREFIX block is present above, ALWAYS qualify every table: "SCHEMA"."TABLE_NAME"
3. Column names MUST be wrapped in double quotes with exact casing: "COLUMN_NAME"
4. Add LIMIT 500 unless the user asks for aggregations or totals
5. For monetary values, use ROUND(value, 2)
6. Prefer readable snake_case aliases for all columns
7. NEVER use SELECT aliases or CTE column names in HAVING or WHERE — HANA does not support this.
   WRONG:  GROUP BY x HAVING total_sales > 0
   CORRECT: Wrap in a subquery and filter with WHERE in the outer query:
   SELECT * FROM ( ... your aggregation ... ) t WHERE t.total_sales > 0
8. NEVER filter on computed/aggregated columns with HAVING if those columns come from a CTE alias.
   Always use a wrapping subquery + WHERE instead.
9. Window functions (ROW_NUMBER, RANK, LAG, LEAD, etc.) MUST be in a subquery
   and cannot coexist with GROUP BY in the same SELECT level — they operate on different result sets.
   Always wrap: SELECT * FROM ( SELECT ..., ROW_NUMBER() OVER (...) AS rn FROM ... ) t WHERE t.rn = 1
   NEVER: SELECT SUM(x), ROW_NUMBER() OVER (...) FROM t GROUP BY y  ← invalid in HANA
   To aggregate a list and also group: use plain STRING_AGG in the GROUP BY query, no OVER().
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
    CRITICAL for UNION ALL: ORDER BY can ONLY reference columns that exist in the final
    output column list. If a column is not in every SELECT of the UNION, it cannot be in ORDER BY.
    Also: NULLS LAST / NULLS FIRST are NOT supported in SAP HANA ORDER BY — remove them entirely.
14. CRITICAL — Column name casing in CTEs and subqueries in HANA:
    HANA is strict about identifier casing. Follow these rules exactly:

    a) When selecting a physical table column with double quotes (e.g. "plant_id"), the CTE output
       column retains the exact lowercase name. You MUST reference it with double quotes in outer CTEs:
         CORRECT: inv."plant_id"
         WRONG:   inv.plant_id   ← HANA folds to INV.PLANT_ID, not found

    b) When defining a computed alias WITHOUT double quotes (e.g. SUM(...) AS total_qty),
       HANA stores it as UPPERCASE. Reference it WITHOUT double quotes:
         CORRECT: inv.total_qty  (HANA resolves to TOTAL_QTY internally)
         WRONG:   inv."total_qty"

    c) SAFEST approach: always double-quote every alias in CTE definitions:
         SELECT "plant_id" AS "plant_id", SUM("on_hand") AS "on_hand" ...
       Then reference ALL CTE columns with double quotes:
         inv."plant_id", inv."on_hand"
       This is consistent and avoids all casing errors.

15. Prefer CTEs (WITH clause) over inline subqueries. Always use approach 14c:
    double-quote every alias in CTE SELECT lists, and reference them with double quotes.
16. CTE alias consistency: every column alias defined in a CTE SELECT must be referenced
    by EXACTLY that alias in outer queries — never by the original source column name.
    If a CTE defines SUM("in_transit") AS "total_in_transit", the outer query MUST use
    cte."total_in_transit" — NOT cte."in_transit". Mismatched aliases cause error 260.
17. CTE names in WITH clause must NEVER be double-quoted — they are unquoted identifiers.
    CORRECT: WITH inventory AS (SELECT ...)
    WRONG:   WITH "inventory" AS (SELECT ...)
    Column names inside the CTE body still require double quotes as per rules 2-3 and 14.
18. Never create a CTE solely to hold a single computed value such as a date.
    Inline ADD_DAYS() directly in WHERE instead:
    CORRECT: WHERE "future_date" <= ADD_DAYS(CURRENT_DATE, 1)
    WRONG:   WITH tgt AS (SELECT ADD_DAYS(CURRENT_DATE, 1) AS d) ... WHERE "future_date" <= td.d
19. When joining a CTE to another table/CTE inside a CTE body, use explicit JOIN syntax.
    HANA does NOT support comma cross-join syntax when one side is a CTE:
    CORRECT: FROM "SCHEMA"."TABLE" AS inv CROSS JOIN cte_name AS td WHERE inv."col" <= td."val"
    WRONG:   FROM "SCHEMA"."TABLE" AS inv, cte_name AS td WHERE inv."col" <= td."val"
20. CRITICAL — Never reference a physical source column name on a CTE alias in the outer query.
    Only reference the alias as defined in that CTE's SELECT list. This is error 260.
    WRONG (causes error 260):
      WITH inv_agg AS (SELECT SUM("in_transit") AS "total_in_transit" ...)
      SELECT inv."in_transit" ...          ← "in_transit" is NOT in the CTE output
    CORRECT:
      WITH inv_agg AS (SELECT SUM("in_transit") AS "total_in_transit" ...)
      SELECT inv."total_in_transit" ...    ← use the CTE alias exactly
    The same rule applies to every column: "on_hand", "allocated", "on_order", etc.
    If you need the raw column in the outer query, select it explicitly in the CTE
    with an alias and reference that alias.

RESPONSE FORMAT (JSON only, no markdown):
{
    "table_name": "exact table name from schema",
    "sql": "SELECT ... FROM \\"TABLE_NAME\\" ...",
    "explanation": "brief reasoning for table and approach",
    "grain": "transactional|aggregated",
    "is_dashboard_ready": true|false,
    "rules_applied": ["list of key rules applied"]
}
"""
        )
    elif db_type == "postgresql":
        return (
            "You are a PostgreSQL expert working with SAP data products.\n"
            + """USER QUESTION:
{question}

AVAILABLE SCHEMA INFORMATION (from RAG registry):
{schema_context}

{business_context}

STRICT POSTGRESQL RULES:
1. Use ONLY tables and columns present in the schema above — never invent names
2. Table names MUST be: public."EXACT_TABLE_NAME" (double quotes, exact casing)
3. Column names MUST be wrapped in double quotes with exact casing: "COLUMN_NAME"
4. Add LIMIT 500 unless the user asks for aggregations or totals
5. For monetary values, use ROUND(value::numeric, 2)
6. Prefer readable snake_case aliases for all columns

RESPONSE FORMAT (JSON only, no markdown):
{
    "table_name": "exact table name from schema",
    "sql": "SELECT ... FROM public.\\"TABLE_NAME\\" ...",
    "explanation": "brief reasoning for table and approach",
    "grain": "transactional|aggregated",
    "is_dashboard_ready": true|false,
    "rules_applied": ["list of key HANA/PG rules applied"]
}
"""
        )

    # New backends (lite multi-DB, 2026-07): reuse the single source of truth for
    # dialect rules from ask_sql_generation, wrapped in Flash's RAG scaffold.
    role_line, strict_rules = _shared_dialect(db_type)
    return role_line + "\n" + _FLASH_SCAFFOLD + strict_rules + _FLASH_RESPONSE_FORMAT


def _safe_json_loads(text: str) -> dict:
    """Parse JSON that may contain unescaped control characters inside string values."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Escape control characters that appear inside JSON string values
    result = []
    in_string = False
    escape_next = False
    _ctrl = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == "\\" and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and (ord(ch) < 0x20 or ord(ch) == 0x7F):
            result.append(_ctrl.get(ch, ""))
        else:
            result.append(ch)
    return json.loads("".join(result))


def generate_sql(
    question: str,
    schema_vs,
    llm,
    db_type: str,
    conversation_history: str = "",
    schema_mode: str = "both",
    hana_schema: str = "",
    allowed_ids: list | None = None,
    user_context: str = "",
) -> dict:
    _mode_to_types = {
        "documents": ["schema_technical", "business_semantic"],
        "yaml": ["yaml_data_product"],
        "both": ["schema_technical", "yaml_data_product"],
    }
    doc_types = _mode_to_types.get(schema_mode, _mode_to_types["both"])

    if len(doc_types) == 1:
        _filter = {"term": {"metadata.doc_type": doc_types[0]}}
    else:
        _filter = {"terms": {"metadata.doc_type": doc_types}}

    # Workspace scope: chunks carry metadata.entity_id (rag_text_renderer), so
    # AND the doc_type filter with an entity-id terms filter (bool/must is
    # supported by the vectorstore's Python post-filter).
    # Scope contract: None = unscoped (whole index); [] = empty scope (terms:[]
    # matches nothing). Branch on `is None`, NOT truthiness, so an empty
    # workspace scope does not silently fall through to the whole index.
    def _scoped(base: dict) -> dict:
        if allowed_ids is None:
            return base
        return {"bool": {"must": [base, {"terms": {"metadata.entity_id": list(allowed_ids)}}]}}

    schema_docs = schema_vs.similarity_search(question, k=5, filter=_scoped(_filter))
    if not schema_docs:
        return {
            "error": "No schema information found. Please ingest schema documentation first.",
            "sql": None,
        }

    schema_context = "\n\n---\n\n".join(
        [
            f"Table: {d.metadata.get('table_name', 'Unknown')}\n"
            f"Layer: {d.metadata.get('layer', '?')} | Grain: {d.metadata.get('grain', '?')} | "
            f"Dashboard Ready: {d.metadata.get('is_dashboard_ready', False)}\n"
            f"Measures: {d.metadata.get('measures', [])}\n"
            f"Dimensions: {d.metadata.get('dimensions', [])}\n\n"
            f"{d.page_content}"
            for d in schema_docs
        ]
    )

    business_docs = schema_vs.similarity_search(
        question, k=2, filter=_scoped({"term": {"metadata.doc_type": "business_semantic"}})
    )
    business_context = ""
    if business_docs:
        business_context = "BUSINESS RULES:\n" + "\n\n".join(
            [
                f"Rules for {d.metadata.get('table_name', 'Unknown')}:\n{d.page_content}"
                for d in business_docs
            ]
        )

    prompt_text = _build_sql_prompt(db_type)

    if hana_schema and db_type == "hana":
        schema_prefix_block = (
            f"HANA SCHEMA PREFIX (MANDATORY — this overrides rule #2 below):\n"
            f'Every table reference MUST be qualified: "{hana_schema}"."TABLE_NAME"\n'
            f'Example: FROM "{hana_schema}"."SILVER_SD_SALES_ORDER" AS t\n'
            f'NEVER write a bare table name without the "{hana_schema}". prefix.\n\n'
        )
        prompt_text = schema_prefix_block + prompt_text
    elif hana_schema and db_type not in ("hana", "postgresql"):
        # New backends: use the dialect's own schema-prefix rule if it has one.
        try:
            from ask_sql_generation.application.prompts.registry import get_dialect

            _d = get_dialect(db_type)
            if _d and _d.schema_prefix:
                prompt_text = _d.schema_prefix(hana_schema) + "\n" + prompt_text
        except Exception:
            pass

    if conversation_history:
        prompt_text = (
            f"CONVERSATION HISTORY (use this to resolve follow-up questions):\n"
            f"{conversation_history}\n\n---\n\n"
        ) + prompt_text

    # Customer + workspace framing (company / SAP version + the active workspace
    # and its business domains). Prepended at the very top so the model frames
    # the answer in the right org + domain terms. Empty when not configured.
    if user_context and user_context.strip():
        prompt_text = f"{user_context.strip()}\n\n---\n\n" + prompt_text

    prompt_text = prompt_text.replace("{question}", question)
    prompt_text = prompt_text.replace("{schema_context}", schema_context)
    prompt_text = prompt_text.replace("{business_context}", business_context or "")

    try:
        response = llm.invoke([HumanMessage(content=prompt_text)])
        text = content_to_text(response).strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        result = _safe_json_loads(text)
        result["schema_used"] = schema_context
        result["schema_docs_meta"] = [d.metadata for d in schema_docs]
        return result
    except json.JSONDecodeError as e:
        return {"error": f"Failed to parse LLM response: {e}", "sql": None}
    except Exception as e:
        err = str(e)
        if "404" in err or "Not Found" in err:
            return {
                "error": (
                    "**404 Not Found** — The LLM deployment was not found in SAP AI Core.\n\n"
                    "Please go to **Setup → LLM & Embeddings** and re-select the deployment."
                ),
                "sql": None,
            }
        if "401" in err or "Unauthorized" in err:
            return {
                "error": "**401 Unauthorized** — Invalid or expired AI Core credentials.",
                "sql": None,
            }
        return {"error": f"Error generating SQL: {e}", "sql": None}


# Iter N — shims removed. Callers now use:
#   - ask_sql_executor.SqlExecutorService.execute_and_format() for execution + formatting,
#   - ask_sql_executor.LLMResultFormatter.no_results_answer() for empty-result text,
# directly. The is_silver_layer helper had no remaining consumers and was
# dropped in the same pass.
