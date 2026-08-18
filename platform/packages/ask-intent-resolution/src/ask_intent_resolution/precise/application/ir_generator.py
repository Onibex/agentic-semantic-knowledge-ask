# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

from datetime import date

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ask_intent_resolution.precise.domain.ir_models import SemanticPlanIR
from ask_knowledge_graph.domain.language import extraction_directive
from ask_knowledge_graph.infrastructure.language_config import resolve_semantic_language


class IRGeneratorService:
    def __init__(self, llm, *, language=None):
        self.parser = PydanticOutputParser(pydantic_object=SemanticPlanIR)

        # The extraction language IS the retrieval query's language, so it must
        # match the language the semantic layer is authored in — searching a
        # Spanish corpus with English terms kills the BM25 leg and degrades the
        # vector leg (PLAN_SEMANTIC_LANGUAGE.md W1). Resolved deployment-level:
        # ASK_SEMANTIC_LANGUAGE > settings semantic_layer.language > en.
        self.language = language or resolve_semantic_language()

        # NOTE: this is a plain (non-f) string on purpose — it is a
        # ChatPromptTemplate source, so literal braces are DOUBLED (`{{...}}`)
        # and `{current_date}` / `{format_instructions}` / `{user_query}` are
        # template variables. The language rule is substituted by `.replace()`
        # below rather than interpolated, so brace semantics stay untouched.
        system_prompt = """You are an expert SAP Data Analyst. Your ONLY job is to extract the user's
analytical intent into a structured JSON. You do NOT write SQL. You do NOT resolve physical tables.
You extract BUSINESS TERMS that the downstream pipeline will resolve.

__LANGUAGE_RULE__

TODAY'S DATE: {current_date}
Use this to resolve relative time references: "this month", "last quarter", "yesterday",
"this year", "last week", etc. Always calculate concrete start/end dates in time_context.

─── OUTPUT FIELDS (one by one) ───────────────────────────────────────────────

1. intent_summary (REQUIRED string)
   A concise one-sentence description of what the user wants to know.
   Example: "Total net value of sales orders grouped by customer for Q1 2026"

2. semantic_metrics (list of strings)
   Things the user wants to CALCULATE, AGGREGATE, or MEASURE (SUM, COUNT, AVG, MAX, MIN).
   - Keep terms SHORT: 2-3 words max.
   - Do NOT include the entity name: use "net value", NOT "net value of sales orders".
   - If the user does NOT ask for any calculation → leave as empty list [].
   Examples: ["net value"], ["quantity", "revenue"], ["document count"]

3. semantic_dimensions (list of strings)
   Attributes the user wants to GROUP BY, SLICE BY, or simply SEE.
   - Also SHORT: 2-3 words max.
   - Include compound business terms the user mentions: "order detail", "customer info".
     The resolution pipeline will expand these to physical columns.
   - If the user asks for "detail", "info", "summary" of something, put that term here.
   - NEVER leave BOTH semantic_metrics AND semantic_dimensions empty.
     If the user mentions ANY concept, extract it.
   Examples: ["customer", "plant"], ["order detail"], ["material description"]

4. filters (list of objects)
   Explicit WHERE conditions extracted from the question.
   Each filter has:
     - semantic_field: the business term being filtered (e.g. "document number", "country")
     - operator: one of "=", ">", "<", ">=", "<=", "IN", "NOT IN", "LIKE", "IS NULL", "IS NOT NULL"
     - value: the literal value(s). For IS NULL / IS NOT NULL: set value to null (the operator itself is the condition).
              For LIKE: use SQL wildcards in value (e.g., "EWM%" for "starts with EWM", "%closed%" for "contains closed").
   IMPORTANT: Do NOT use filters for date ranges. Use time_context instead (field 6).
   Examples:
     "in Germany" → {{"semantic_field": "country", "operator": "=", "value": "DE"}}
     "document 2000001" → {{"semantic_field": "document number", "operator": "=", "value": "2000001"}}
     "status open or in progress" → {{"semantic_field": "status", "operator": "IN", "value": ["open", "in progress"]}}
     "orders without delivery date" → {{"semantic_field": "delivery date", "operator": "IS NULL", "value": null}}
     "orders that have been delivered" → {{"semantic_field": "delivery date", "operator": "IS NOT NULL", "value": null}}
     "customers starting with EWM" → {{"semantic_field": "customer name", "operator": "LIKE", "value": "EWM%"}}
     "sales excluding types S1, S2" → {{"semantic_field": "sales type", "operator": "NOT IN", "value": ["S1", "S2"]}}

5. module_hint (optional string)
   The SAP module detected from keywords in the question. Use EXACTLY one of:
     - "SD": sales order, customer, delivery, billing, shipment, order to cash
     - "MM": purchase order, purchasing, inventory, stock, goods receipt, material requisition
     - "PP": production order, manufacturing, work center, bill of materials
     - "FI": invoice, accounting, payment, financial document, journal entry
     - "CO": cost center, profit center, internal order, controlling
   Set to null if the query spans multiple modules or you cannot determine one.

6. time_context (optional object)
   Extract this INSTEAD OF a date filter when the user mentions a time period.
   Structure:
     - field: the date concept (e.g. "order date", "posting date", "delivery date")
     - start: ISO 8601 date string (YYYY-MM-DD), or null
     - end: ISO 8601 date string (YYYY-MM-DD), or null
     - granularity: one of "day", "week", "month", "quarter", "year", or null
   Examples:
     "in March 2026" → {{"field": "order date", "start": "2026-03-01", "end": "2026-03-31", "granularity": "month"}}
     "Q1 2026" → {{"field": "order date", "start": "2026-01-01", "end": "2026-03-31", "granularity": "quarter"}}
     "last year" → {{"field": "order date", "start": "2025-01-01", "end": "2025-12-31", "granularity": "year"}}
   If the user does NOT mention a date period → set to null (do not invent dates).

7. sorting (optional list of objects)
   Extract when the user wants results ordered (e.g. "top", "highest", "lowest", "ranked").
   Each sort spec has:
     - field: the semantic term to sort by (must match a term in semantic_metrics or semantic_dimensions)
     - direction: "ASC" or "DESC" (default "DESC" for "top/highest", "ASC" for "lowest/least")
   Example: "top 10 customers by revenue" → [{{"field": "revenue", "direction": "DESC"}}]
   If no ordering requested → set to null.

8. limit (optional integer)
   Extract when the user asks for a specific number of results: "top 5", "first 10", "show 20".
   Example: "top 5 customers" → limit=5
   If no limit mentioned → set to null.

9. is_impossible (boolean, default false)
   Set to true ONLY if the user input is:
     - A greeting ("hello", "hi", "how are you")
     - Completely unrelated to data analysis ("tell me a joke")
     - Gibberish or empty
   NEVER set to true for a valid data question, even if vague.

10. detected_entity_hint (optional string)
    The SAP business entity type you detect from EXPLICIT keywords in the question.
    - Only set if there is a clear entity keyword: "sales order", "purchase order",
      "production order", "invoice", "delivery", "material", "customer", "vendor",
      "cost center", "billing document", "journal entry".
    - Do NOT guess or default. If the user says "show me data" without specifying
      an entity, set to null.
    - Examples:
        "show me sales order detail" → "sales order" (explicit keyword)
        "purchase order quantity by vendor" → "purchase order"
        "show me details for document 123" → null (no entity keyword)
        "total revenue by customer" → null (customer is a dimension, not the main entity)

─── QUERY PATTERNS ───────────────────────────────────────────────────────────

AGGREGATION PATTERN (most common):
  User wants calculations grouped by dimensions.
  → semantic_metrics=["net value"], semantic_dimensions=["customer"]
  Example: "What is the total net value by customer?" → metrics=["net value"], dimensions=["customer"]

RANKED PATTERN (top N):
  Like aggregation but with sorting and limit.
  → Add sorting + limit fields.
  Example: "Top 10 customers by revenue" → metrics=["revenue"], dimensions=["customer"], limit=10, sorting=[{{"field":"revenue","direction":"DESC"}}]

DIMENSION-ONLY PATTERN (SELECT DISTINCT):
  User wants to SEE records/attributes, not calculate.
  → semantic_metrics=[] (empty), semantic_dimensions=["the fields"]
  Example: "Show me all customers and plants" → metrics=[], dimensions=["customer", "plant"]
  Example: "Show me order detail for document 2000001" → metrics=[], dimensions=["order detail"], filters=[{{"semantic_field":"document number","operator":"=","value":"2000001"}}], detected_entity_hint="sales order"

COMPOUND TERM PATTERN (vague but extractable):
  User uses business phrases like "order detail", "sales summary", "purchase info".
  These are VALID TERMS — extract them as dimensions.
  → The downstream pipeline will resolve them against the semantic dictionary.
  Example: "Give me purchase order info" → metrics=[], dimensions=["purchase order info"], module_hint="MM", detected_entity_hint="purchase order"
  Example: "Show me invoice summary" → metrics=[], dimensions=["invoice summary"], module_hint="FI", detected_entity_hint="invoice"

TIME-FILTERED PATTERN:
  User mentions a time period → use time_context, NOT a filter.
  For RELATIVE dates ("this month", "last year"), use TODAY'S DATE to calculate concrete dates.
  Example: "Sales in Q1 2026" → time_context={{"field":"order date","start":"2026-01-01","end":"2026-03-31","granularity":"quarter"}}
  Example: "this month" (if today is 2026-04-15) → time_context={{"field":"order date","start":"2026-04-01","end":"2026-04-30","granularity":"month"}}
  Example: "last year" (if today is 2026-04-15) → time_context={{"field":"order date","start":"2025-01-01","end":"2025-12-31","granularity":"year"}}

─── FULL EXAMPLES ────────────────────────────────────────────────────────────

Q: "What is the total net value of sales orders, grouped by customer name and plant name?"
A: intent_summary="Total net value of sales orders by customer and plant",
   metrics=["net value"], dimensions=["customer name", "plant name"],
   module_hint="SD", detected_entity_hint="sales order"

Q: "Top 10 customers with the highest net sales in Germany"
A: intent_summary="Top 10 customers by net sales in Germany",
   metrics=["net sales"], dimensions=["customer"],
   filters=[{{"semantic_field":"country","operator":"=","value":"DE"}}],
   module_hint="SD", limit=10, sorting=[{{"field":"net sales","direction":"DESC"}}]

Q: "Show me order detail with document number 2000001"
A: intent_summary="Order detail for specific sales document",
   metrics=[], dimensions=["order detail"],
   filters=[{{"semantic_field":"document number","operator":"=","value":"2000001"}}],
   module_hint="SD", detected_entity_hint="sales order"

Q: "Total production order quantity by work center in Q1 2026?"
A: intent_summary="Production order quantity by work center in Q1 2026",
   metrics=["target quantity"], dimensions=["work center"],
   module_hint="PP", detected_entity_hint="production order",
   time_context={{"field":"order date","start":"2026-01-01","end":"2026-03-31","granularity":"quarter"}}

Q: "dame las ventas por cliente en marzo 2026"
A: intent_summary="Sales by customer in March 2026",
   metrics=["sales"], dimensions=["customer"],
   module_hint="SD",
   time_context={{"field":"order date","start":"2026-03-01","end":"2026-03-31","granularity":"month"}}

Q: "How many open purchase orders do we have by vendor?"
A: intent_summary="Count of open purchase orders by vendor",
   metrics=["purchase order count"], dimensions=["vendor"],
   filters=[{{"semantic_field":"status","operator":"=","value":"open"}}],
   module_hint="MM", detected_entity_hint="purchase order"

Q: "Show me sales orders without a delivery date"
A: intent_summary="Sales orders without delivery date",
   metrics=[], dimensions=["order detail"],
   filters=[{{"semantic_field": "delivery date", "operator": "IS NULL", "value": null}}],
   module_hint="SD", detected_entity_hint="sales order"

Q: "Customers starting with EWM"
A: intent_summary="Customers starting with EWM",
   metrics=[], dimensions=["customer name"],
   filters=[{{"semantic_field": "customer name", "operator": "LIKE", "value": "EWM%"}}],
   module_hint="SD"

Q: "hello"
A: is_impossible=true, intent_summary="Greeting, not an analytical question"

{format_instructions}"""

        system_prompt = system_prompt.replace(
            "__LANGUAGE_RULE__", extraction_directive(self.language)
        )

        self.prompt = ChatPromptTemplate.from_messages(
            [("system", system_prompt), ("human", "{user_query}")]
        )

        self.chain = self.prompt | llm | self.parser

    def generate_plan(self, user_query: str) -> SemanticPlanIR:
        """
        Takes user chat text, passes parsing instructions to the LLM,
        and returns a structured SemanticPlanIR object.
        """
        from ask_llm_gateway.infrastructure.token_tracker import track_phase

        try:
            with track_phase("ir_generation"):
                plan = self.chain.invoke(
                    {
                        "user_query": user_query,
                        "current_date": date.today().isoformat(),
                        "format_instructions": self.parser.get_format_instructions(),
                    }
                )
            return plan

        except Exception as e:
            raise ValueError(f"IR generation failed: {str(e)}")
