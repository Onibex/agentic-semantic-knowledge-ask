# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
src/pipeline_v2/application/entity_selector.py
─────────────────────────────────────────────────────────────────────────────
EntitySelectorService — LLM call #1: ve el catálogo Silver+Gold (filtrado por
data product activo) y produce un Semantic Plan IR v2 (spec Sec. 10.1).

Responsabilidades:
  1. Construye prompt con system (rules + catalog + few-shots) + user (question).
  2. Invoca LLM (Claude 4.6 Sonnet) con temperature=0.
  3. Parsea el JSON, valida contra el pydantic SemanticPlanIRv2.
  4. Valida IDs: base_entity + traversals[] deben existir en el catálogo.
  5. Retry (max 2) con feedback si el LLM alucina IDs o devuelve JSON inválido.
  6. Registra llamadas en TokenTracker bajo phase "entity_selection".

El system prompt es ESTABLE (mismo catálogo → misma cadena literal) para
aprovechar prompt caching de Claude. Sólo la user message varía por query.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage

from ask_intent_resolution.smart.application.catalog_service import CatalogService
from ask_intent_resolution.smart.domain.catalog import Catalog
from ask_intent_resolution.smart.domain.ir import SelectorOutput, SemanticPlanIRv2
from ask_llm_gateway.infrastructure.response_utils import content_to_text
from ask_llm_gateway.infrastructure.token_tracker import track_phase

# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates — ESTABLES (para prompt caching)
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_RULES = """You are the Entity Selector for the Onibex ASK pipeline.

ROLE
----
Given a user business question about enterprise data, produce a Semantic Plan
Intermediate Representation (IR) that identifies:
  1. The base entity (the primary Silver/Gold table the query operates on).
  2. Optional traversals (other entities the query needs to reach via JOINs).
  3. Measures and dimensions expressed as business terms.
  4. Filters, time context, sorting, output shape, and limit.

You do NOT generate SQL. You do NOT resolve physical column names. A downstream
SQL generator uses your IR + the selected entities' schema to compose the SQL.

CONSTRAINTS
-----------
- base_entity and every id in traversals MUST be a valid ID from the ENTITY
  CATALOG section below. Do NOT invent IDs. Do NOT guess.
- ALWAYS prefer Gold (layer: gold) entities as base_entity over Silver when a
  Gold entity covers the same business domain. Gold entities are pre-joined,
  denormalized, and optimized for analytics — they exist precisely to avoid
  multi-table JOINs. Only fall back to Silver when no Gold entity is relevant.
- Prefer `fact` entities as base_entity when the question is about measurements
  (totals, counts, sums, comparisons, trends over time).
- Use `dimension` entities in traversals when they provide attributes the query
  needs to filter or group by (plants, materials, customers, etc.).
- Dimensions/measures in the IR are BUSINESS TERMS (e.g., "plant", "material",
  "on_hand_quantity"). Do not try to match physical column names.
- If the question cannot be resolved from the catalog, set base_entity to empty
  string and explain in `intent` and `reasoning`.
- Keep `reasoning` under 250 characters.

OUTPUT SCHEMA (JSON, no wrappers, no commentary)
------------------------------------------------
{
  "intent": "string - NL description of the query for audit",
  "base_entity": "string - entity ID from catalog (or empty if unresolvable)",
  "measures": ["string", ...],
  "dimensions": ["string", ...],
  "filters": [
    {"field": "string", "operator": "EQ|NE|GT|GE|LT|LE|IN|NOT_IN|LIKE|NOT_LIKE|IS_NULL|IS_NOT_NULL|BETWEEN", "value": any or null, "values": [any, ...] or null}
  ],
  "time_context": {
    "field": "string",
    "start": "YYYY-MM-DD" or null,
    "end": "YYYY-MM-DD" or null,
    "granularity": "day|week|month|quarter|year" or null
  } or null,
  "traversals": ["entity_id", ...],
  "output_shape": "table|scalar|time_series|ranked_list",
  "sorting": [{"field": "string", "direction": "ASC|DESC"}],
  "limit": integer or null,
  "module_hints": ["SD", "MM", "FI", ...],
  "reasoning": "string - brief explanation of entity selection (<250 chars)"
}

FORMAT RULES
------------
- Respond with ONLY the JSON object. No markdown fences, no prose.
- If a field doesn't apply, use null or empty list as appropriate.
- Use ISO-8601 for dates (YYYY-MM-DD).
"""


_FEW_SHOTS = """EXAMPLES
--------

Example 1 — Gold preferred over Silver when it covers the same domain:
Question: "Show me the latest sales orders."
Output:
{"intent":"Latest sales orders","base_entity":"gold_s4h_open_order_tracker","measures":[],"dimensions":["sales_order","customer","plant","order_status"],"filters":[],"time_context":null,"traversals":[],"output_shape":"table","sorting":[{"field":"order_date","direction":"DESC"}],"limit":10,"module_hints":["SD"],"reasoning":"Gold entity covers sales order domain and is denormalized — preferred over Silver to avoid unnecessary JOINs."}

Example 2 — single-fact aggregation with time filter:
Question: "What was the total purchased amount in Q1 2026?"
Output:
{"intent":"Total purchased amount for Q1 2026","base_entity":"silver_ecc_mm_purchase_order","measures":["purchased_amount"],"dimensions":[],"filters":[],"time_context":{"field":"order_date","start":"2026-01-01","end":"2026-03-31","granularity":"quarter"},"traversals":[],"output_shape":"scalar","sorting":[],"limit":null,"module_hints":["MM"],"reasoning":"Single-fact aggregation over purchase orders with quarterly filter."}

Example 3 — cross-entity join with dimension and conditional filter:
Question: "Which plants hold excess stock for materials with no open purchase orders?"
Output:
{"intent":"Plants with excess stock for materials having no open POs","base_entity":"silver_ecc_mm_inv_mov_stock","measures":["on_hand_stock"],"dimensions":["plant","material"],"filters":[{"field":"po_status","operator":"NOT_IN","value":null,"values":["OPEN"]}],"time_context":null,"traversals":["silver_ecc_sd_plant","silver_ecc_mm_purchase_order"],"output_shape":"ranked_list","sorting":[{"field":"on_hand_stock","direction":"DESC"}],"limit":null,"module_hints":["MM","SD"],"reasoning":"Stock as base fact; traverse plant dim and PO fact to apply conditional filter."}

Example 4 — unresolvable question (not in catalog):
Question: "Give me the monthly revenue from customer Acme Corp."
Output:
{"intent":"Monthly revenue by customer - unresolvable with current catalog (no sales invoice entity in scope)","base_entity":"","measures":[],"dimensions":[],"filters":[],"time_context":null,"traversals":[],"output_shape":"table","sorting":[],"limit":null,"module_hints":[],"reasoning":"No sales/invoice fact entity available in the active catalog; cannot resolve."}
"""


_USER_PROMPT_TEMPLATE = """[RECENT CONVERSATION]
{history}

[USER QUESTION]
{question}

[OUTPUT]
Respond with ONLY the JSON object matching the schema. No markdown, no prose.
"""


class EntitySelectorService:
    """LLM-as-retriever: selecciona entities del catálogo + produce IR v2."""

    MAX_RETRIES = 2
    PHASE_TAG = "entity_selection"

    def __init__(self, llm, catalog_service: CatalogService):
        """
        Args:
            llm: Chat LLM (Claude 4.6 Sonnet, temperature=0 recomendado).
            catalog_service: CatalogService — fuente del catálogo cacheado.
        """
        self._llm = llm
        self._catalog_service = catalog_service

    # ── Public API ──────────────────────────────────────────────────────────

    def select(
        self,
        question: str,
        *,
        allowed_ids: set[str] | None = None,
        conversation_history: str = "",
        organization_context: str | None = None,
    ) -> SelectorOutput:
        """
        Main entry point.

        Args:
            question: pregunta del usuario.
            allowed_ids: scope del data product activo. Si None, usa catálogo completo.
            conversation_history: historial opcional para follow-up queries.
            organization_context: snippet del cliente (company, SAP version, módulos)
                que se prepende al system prompt. None cuando el admin no ha llenado
                la página Organization.

        Returns:
            SelectorOutput con IR + validación + retry_count.
        """
        catalog = self._catalog_service.get_catalog(allowed_ids=allowed_ids)
        valid_ids = catalog.valid_ids()

        system_prompt = self._build_system_prompt(catalog, organization_context)
        user_prompt = self._build_user_prompt(question, conversation_history)

        last_ir: SemanticPlanIRv2 | None = None
        last_invalid: list[str] = []

        for attempt in range(self.MAX_RETRIES + 1):
            raw_response = self._invoke_llm(system_prompt, user_prompt)
            ir, invalid = self._parse_and_validate(raw_response, valid_ids)

            if ir is not None and not invalid:
                return SelectorOutput(
                    ir=ir,
                    invalid_entity_ids=[],
                    retry_count=attempt,
                )

            last_ir = ir
            last_invalid = invalid

            if attempt < self.MAX_RETRIES:
                user_prompt = self._retry_prompt(question, conversation_history, ir, invalid)

        fallback_ir = last_ir or SemanticPlanIRv2(
            intent="Could not resolve query after retries",
            base_entity="",
            reasoning="Selector exhausted retries; returning empty IR.",
        )
        return SelectorOutput(
            ir=fallback_ir,
            invalid_entity_ids=last_invalid,
            retry_count=self.MAX_RETRIES,
        )

    # ── internals ────────────────────────────────────────────────────────────

    def _build_system_prompt(
        self, catalog: Catalog, organization_context: str | None = None
    ) -> str:
        """System prompt estable: org context (optional) + rules + catalog + few-shots.

        Org context goes FIRST so the LLM sees the customer's environment
        before any of the generic rules — primes it to frame answers for that
        specific SAP install. Stays out of the cached-prompt portion (catalog
        + few-shots) because it changes whenever the admin edits Organization.
        """
        catalog_text = self._catalog_service.render_as_prompt_context(catalog)
        parts: list[str] = []
        if organization_context:
            parts.append(organization_context)
        parts.append(_SYSTEM_RULES)
        parts.append(catalog_text)
        parts.append(_FEW_SHOTS)
        return "\n\n".join(parts)

    @staticmethod
    def _build_user_prompt(question: str, history: str) -> str:
        return _USER_PROMPT_TEMPLATE.format(
            history=history.strip() if history else "(none)",
            question=question.strip(),
        )

    def _invoke_llm(self, system_prompt: str, user_prompt: str) -> str:
        """LLM call wrapped in track_phase for token accounting.

        Merges system + user into a single HumanMessage so this works with
        GPT-based SAP AI Core deployments that reject the `system` role (400).
        """
        with track_phase(self.PHASE_TAG):
            response = self._llm.invoke(
                [HumanMessage(content=f"{system_prompt}\n\n{user_prompt}")]
            )
        return content_to_text(response)

    @staticmethod
    def _parse_and_validate(
        raw: str, valid_ids: set[str]
    ) -> tuple[SemanticPlanIRv2 | None, list[str]]:
        """
        Parse raw LLM output to SemanticPlanIRv2 + validate entity IDs.

        Returns:
            (ir, invalid_ids). If ir is None, parsing failed (JSON or schema).
            If ir is not None but invalid_ids is non-empty, LLM hallucinated IDs.
        """
        text = (raw or "").strip()

        # Strip markdown code fences if present (no debería, pero defensivo)
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
            # Remove trailing fence if present
            if text.endswith("```"):
                text = text[:-3].strip()

        # Find first { and last } — tolera texto antes/después
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace == -1 or last_brace == -1 or last_brace < first_brace:
            return None, []
        text = text[first_brace : last_brace + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None, []

        try:
            ir = SemanticPlanIRv2.model_validate(data)
        except Exception:
            return None, []

        invalid: list[str] = []
        if ir.base_entity and ir.base_entity not in valid_ids:
            invalid.append(ir.base_entity)
        for tid in ir.traversals:
            if tid not in valid_ids:
                invalid.append(tid)

        return ir, invalid

    @staticmethod
    def _retry_prompt(
        question: str,
        history: str,
        prev_ir: SemanticPlanIRv2 | None,
        invalid_ids: list[str],
    ) -> str:
        """Feedback prompt cuando hubo IDs inválidos o JSON malformado."""
        parts: list[str] = []
        parts.append("[RETRY] Your previous response had issues:")
        if invalid_ids:
            parts.append(f"- These entity IDs do not exist in the ENTITY CATALOG: {invalid_ids}")
            parts.append("  Pick ONLY from the IDs listed in the catalog above.")
        else:
            parts.append("- The response was not valid JSON matching the required schema.")
            parts.append("  Respond with ONLY a single valid JSON object, no prose.")
        parts.append("")
        parts.append(f"[RECENT CONVERSATION]\n{history.strip() if history else '(none)'}")
        parts.append("")
        parts.append(f"[USER QUESTION]\n{question.strip()}")
        parts.append("")
        parts.append("[OUTPUT]\nRespond with ONLY the corrected JSON object.")
        return "\n".join(parts)
