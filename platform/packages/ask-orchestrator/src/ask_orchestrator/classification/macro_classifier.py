"""
ask_orchestrator/classification/macro_classifier.py
─────────────────────────────────────────────────────────────────────────────
Macro intent classification — promoted to the orchestrator in Iter 2.

Why this lives here (and not in ask-intent-resolution):
  - Classification runs BEFORE the strategies pick. It is a routing decision,
    conceptually owned by the orchestrator (per ADR-011).
  - The legacy classifier remains in legacy/src/pipeline/application/
    because the legacy v1 ask_graph still consumes it internally; we copy
    the prompt + schema verbatim here so the orchestrator does not have to
    import src.* (boundary enforced by import-linter).

Iter 2 contract change
  - The legacy enum has 4 values: SCHEMA_QUERY, DOCS_QUERY, SQL_EXECUTION,
    DASHBOARD_GEN. The orchestrator's API contract now exposes only 4 too,
    but DASHBOARD_GEN is FOLDED into SQL_EXECUTION because dashboard
    rendering is a UI concern, not a backend intent. ACTION_EXECUTION
    stays reserved for Iter 7.
"""

from __future__ import annotations

import json
import logging
import threading
from enum import Enum
from pathlib import Path
from typing import Literal

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from ..models.responses import MacroIntent

logger = logging.getLogger(__name__)


class _LegacyMacroIntent(str, Enum):
    """Internal — matches the legacy classifier output. Mapped to MacroIntent before exposure."""

    SCHEMA_QUERY = "SCHEMA_QUERY"
    DOCS_QUERY = "DOCS_QUERY"
    SQL_EXECUTION = "SQL_EXECUTION"
    DASHBOARD_GEN = "DASHBOARD_GEN"
    ACTION_EXECUTION = "ACTION_EXECUTION"


class _ClassifierOutput(BaseModel):
    intent: _LegacyMacroIntent = Field(...)
    confidence: Literal["high", "medium", "low"] = Field(...)
    reasoning: str = Field(...)


_SYSTEM_TEMPLATE = """
You are a macro-intent classifier for "ASK Agentic IA", a natural language
interface to SAP S/4HANA data (PostgreSQL / HANA).

Your ONLY task is to classify the user's question into ONE of the five
permitted categories below. Read every word carefully before deciding.

──────────────────────────────────────────────────────────────
CATEGORIES
──────────────────────────────────────────────────────────────

1. SCHEMA_QUERY
   → Questions about SAP table structures, column names, data types,
     primary keys, relationships between tables, or what fields exist.
   Examples:
     - "What columns does table VBAK have?"
     - "List all tables related to materials in SAP"

2. DOCS_QUERY
   → Questions about SAP business processes, functional documentation,
     KPI definitions, business meanings, or procedural "how-to" guides.
   Examples:
     - "How do I create a purchase order in SAP?"
     - "Explain the order-to-cash process"

3. SQL_EXECUTION
   → Analytical questions that need to RETRIEVE or AGGREGATE transactional
     data: totals, counts, averages, specific records, filtered lists.
     This is the DEFAULT for data questions that are NOT dashboards.
   Examples:
     - "Show me net value of sales orders by customer in Q1 2026"
     - "How many open purchase orders are there this month?"

4. DASHBOARD_GEN
   → Requests that EXPLICITLY ask for multiple charts, panels, a dashboard,
     or a visual overview containing several metrics at once.
   IMPORTANT: A single chart or table is NOT a dashboard → use SQL_EXECUTION.
   Examples:
     - "Create a dashboard with 4 charts for Q1 sales"
     - "I want a visual overview of our inventory KPIs with multiple panels"

5. ACTION_EXECUTION
   → Requests that WRITE, CREATE, UPDATE, or DELETE data in SAP — transactional
     write operations that modify the SAP system state via OData/API.
   Keywords: create, make, add, place, update, change, modify, delete, cancel,
             block, set, post, confirm, release, reject, submit.
   Examples:
     - "Create a sales order for customer X, type TA, sales org 1710"
     - "Update the quantity on sales order 12345 item 10 to 50"
     - "Cancel sales order 99001"
     - "Add a new line item to order 12345"
   IMPORTANT: If the request is about WRITING/MODIFYING data → ACTION_EXECUTION,
              even if it mentions specific field values or SAP objects.

──────────────────────────────────────────────────────────────
DECISION RULES
──────────────────────────────────────────────────────────────
• If the question contains write verbs (create, update, delete, cancel, add,
  place, post, confirm, release) acting on SAP objects → ACTION_EXECUTION.
• If the question mentions BOTH data retrieval AND "dashboard"/"multiple charts"
  → prefer DASHBOARD_GEN.
• If uncertain between SQL_EXECUTION and DOCS_QUERY, check: does the answer
  require querying a database? Yes → SQL_EXECUTION. No → DOCS_QUERY.
• Greetings, tests, or nonsensical inputs → SQL_EXECUTION with low confidence.

{format_instructions}
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Mapping between the internal 4-value enum and the public 4-value contract.
# DASHBOARD_GEN is folded into SQL_EXECUTION because dashboard rendering is a
# UI concern handled by the SQL_EXECUTION path's strategies.
# ─────────────────────────────────────────────────────────────────────────────
_LEGACY_TO_PUBLIC: dict[_LegacyMacroIntent, MacroIntent] = {
    _LegacyMacroIntent.SCHEMA_QUERY: "SCHEMA_QUERY",
    _LegacyMacroIntent.DOCS_QUERY: "DOCS_QUERY",
    _LegacyMacroIntent.SQL_EXECUTION: "SQL_EXECUTION",
    _LegacyMacroIntent.DASHBOARD_GEN: "SQL_EXECUTION",
    _LegacyMacroIntent.ACTION_EXECUTION: "ACTION_EXECUTION",
}


class MacroIntentClassifier:
    """LLM-backed classifier with a lazy module-scope LLM bundle."""

    _chain = None
    # LLM config fingerprint the cached chain was built from. The chain pins a
    # ChatLiteLLM whose model is baked in at construction, so it must be
    # rebuilt when an admin switches the active LLM (see factory.llm_revision).
    _chain_revision: str | None = None
    _lock = threading.Lock()

    @classmethod
    def reset(cls) -> bool:
        """Drop the cached prompt|llm|parser chain. Returns True if a chain
        had been cached."""
        with cls._lock:
            had = cls._chain is not None
            cls._chain = None
            cls._chain_revision = None
            return had

    @classmethod
    def _get_chain(cls):
        from ask_llm_gateway.application.factory import llm_revision

        revision = llm_revision()
        if cls._chain is not None and cls._chain_revision == revision:
            return cls._chain
        with cls._lock:
            if cls._chain is not None and cls._chain_revision == revision:
                return cls._chain
            from ask_llm_gateway.application.factory import build_llm

            cfg_path = Path("config/settings.json")
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            llm = build_llm(cfg)

            parser = PydanticOutputParser(pydantic_object=_ClassifierOutput)
            prompt = ChatPromptTemplate.from_messages(
                [("system", _SYSTEM_TEMPLATE), ("human", "{question}")]
            )
            cls._chain = (prompt | llm | parser, parser)
            cls._chain_revision = revision
            return cls._chain

    def classify(self, question: str) -> MacroIntent:
        """Return one of the public MacroIntent values (DASHBOARD_GEN is folded)."""
        if not question or not question.strip():
            raise ValueError("question must not be empty")

        chain, parser = self._get_chain()
        try:
            output: _ClassifierOutput = chain.invoke(
                {
                    "question": question.strip(),
                    "format_instructions": parser.get_format_instructions(),
                }
            )
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning("macro classifier failed (%s) — defaulting to SQL_EXECUTION", exc)
            return "SQL_EXECUTION"

        public = _LEGACY_TO_PUBLIC[output.intent]
        logger.info(
            "macro classifier",
            extra={
                "legacy_intent": output.intent.value,
                "public_intent": public,
                "confidence": output.confidence,
            },
        )
        return public
