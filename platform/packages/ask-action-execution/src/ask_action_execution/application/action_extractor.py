"""
LlmActionExtractor — extracts a structured ``ExtractedAction`` from a
natural-language SAP write request.

Dynamic mode: lists available tools from the MCP server and builds the prompt
from the live contract, so any API uploaded to Contracts is automatically
usable without code changes.

Fallback mode: if the MCP server is unreachable, falls back to the hardcoded
Sales-Order prompt (backwards-compatible).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from ..domain.models import ExtractedAction

logger = logging.getLogger(__name__)

_TOOLS_CACHE_TTL = 300  # seconds — refresh tool list every 5 minutes


# ── Dynamic prompt (built from live MCP tool list) ────────────────────────────

_DYNAMIC_PROMPT = """\
You are a SAP S/4HANA integration assistant. Map the user's request to the
correct MCP tool call using ONLY the tools listed below.

User request: {question}

Available tools (write operations only):
{tools_block}

Rules:
- Choose the single best matching tool.
- Use SAP field names exactly as shown (PascalCase).
- For dates use ISO format (YYYY-MM-DD).
- For quantities use decimal strings ("10.000").
- For update/delete: put the entity key in "path" (e.g. "('{{key}}')").
- Omit any keys that the user did not provide.
- For CSRF-protected endpoints include "headers": {{"If-Match": "*"}} on update/delete.

Key SAP field name reference:
A_SalesOrder_create body fields:
- customer / sold-to party → SoldToParty
- order type (e.g. OR, ZOR) → SalesOrderType
- sales org / sales organization → SalesOrganization
- distribution channel → DistributionChannel
- division → OrganizationDivision
- customer reference / PO number → PurchaseOrderByCustomer
- items → to_Item array with: Material, RequestedQuantity (decimal string),
  RequestedQuantitySAPUnit (e.g. "ST"), RequestedQuantityISOUnit (e.g. "PCE")
A_SalesOrderItem_delete / A_SalesOrderItem_update path format:
- path must be: (SalesOrder='<order>',SalesOrderItem='<item>')
- example: path "(SalesOrder='0000006041',SalesOrderItem='000020')"
A_ProductionOrder_2_create body fields (IMPORTANT — use these exact names):
- order type (e.g. YBM1, PP01, PP03) → ManufacturingOrderType
- material / product → Material
- plant / production plant / MRP plant → ProductionPlant
- quantity / total quantity → TotalQuantity (decimal string, e.g. "100.000")
- unit of measure → ProductionUnit (e.g. "PC", "TO", "KG", "ST")
- planned start date → MfgOrderPlannedStartDate (ISO YYYY-MM-DD)
- planned end date → MfgOrderPlannedEndDate (ISO YYYY-MM-DD)
DO NOT use OrderType, MRPPlant, or Quantity for production orders.

Respond with JSON only — no markdown fences:
{{
  "tool": "<exact tool name from the list>",
  "args": {{
    "body": {{...}},
    "path": "...",
    "headers": {{...}}
  }}
}}
Only include the keys that apply (body for create, path+body for update, path for delete)."""


# ── Fallback prompt (hardcoded Sales-Order actions) ───────────────────────────

_FALLBACK_PROMPT = """\
You are a SAP S/4HANA assistant. Extract the WRITE action and parameters from
the user request. Only write operations (create, update, delete) are handled.

User request: {question}

Available actions:
- create_order: create a new sales order header, optionally with items
  (params: sold_to_party, sales_order_type, sales_organization,
   distribution_channel, organization_division, requested_delivery_date,
   currency, customer_po, items: [{{material, quantity, quantity_unit, plant}}])
- update_header: update fields on an existing sales order header
  (params: sales_order_id, plus header fields e.g. RequestedDeliveryDate)
- create_item: add a material to an existing sales order
  (params: sales_order_id, material, quantity, quantity_unit, plant)
- update_item: update an existing line item
  (params: sales_order_id, item_id, RequestedQuantity,
   RequestedQuantitySAPUnit, etc.)
- delete_item: delete a line item
  (params: sales_order_id, item_id)

SAP item numbering: 1st item = "10", 2nd = "20", 3rd = "30", etc.

Respond JSON only:
{{
    "action": "create_order|update_header|create_item|update_item|delete_item",
    "params": {{}}
}}"""


# ── Helpers ───────────────────────────────────────────────────────────────────

_WRITE_OPS = {"create", "update", "delete"}


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text


def _to_text(response: Any) -> str:
    try:
        from ask_llm_gateway.infrastructure.response_utils import content_to_text  # type: ignore

        return content_to_text(response)
    except ImportError:
        c = getattr(response, "content", response)
        return c if isinstance(c, str) else str(c)


def _build_tools_block(tools: list[dict]) -> str:
    """Format the MCP tool list into a compact prompt section."""
    lines: list[str] = []
    for tool in tools:
        name = str(tool.get("name") or "")
        # Filter to write operations only
        op = name.rsplit("_", 1)[-1] if "_" in name else ""
        if op not in _WRITE_OPS:
            continue
        desc = str(tool.get("description") or "")
        schema = tool.get("inputSchema") or {}
        props = schema.get("properties") or {}
        body_fields = list(((props.get("body") or {}).get("properties") or {}).keys())[:60]
        field_str = ", ".join(body_fields) if body_fields else ""
        lines.append(f"- {name}: {desc}")
        if field_str:
            lines.append(f"  body fields: {field_str}")
    return "\n".join(lines) if lines else "(no write tools registered — upload a contract first)"


# ── Extractor ─────────────────────────────────────────────────────────────────


class LlmActionExtractor:
    """Dynamic extractor backed by live MCP tool discovery.

    On each extract() call it checks a 5-minute tool cache. When tools are
    available it builds a prompt from the live contract; when the MCP server
    is unreachable it falls back to the hardcoded Sales-Order prompt so
    existing demos keep working.
    """

    def __init__(self, llm: Any, adapter: Any = None) -> None:
        self._llm = llm
        self._adapter = adapter          # SapMcpAdapter | None
        self._tools_cache: list[dict] | None = None
        self._cache_ts: float = 0.0
        self._lock = threading.Lock()

    # ── Tool discovery ────────────────────────────────────────────────────────

    def _get_tools(self) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            if self._tools_cache is not None and (now - self._cache_ts) < _TOOLS_CACHE_TTL:
                return self._tools_cache

        if self._adapter is None:
            return []
        try:
            tools = self._adapter.available_tools()
        except Exception as exc:
            logger.warning("MCP tool discovery failed (falling back to static prompt): %s", exc)
            return []

        with self._lock:
            self._tools_cache = tools
            self._cache_ts = time.monotonic()
        logger.info("MCP tool cache refreshed — %d tools available", len(tools))
        return tools

    def invalidate_cache(self) -> None:
        """Force the next extract() call to re-fetch tools from MCP."""
        with self._lock:
            self._tools_cache = None
            self._cache_ts = 0.0

    # ── Extraction ────────────────────────────────────────────────────────────

    def extract(self, question: str) -> ExtractedAction:
        tools = self._get_tools()

        if tools:
            return self._extract_dynamic(question, tools)
        return self._extract_fallback(question)

    def _extract_dynamic(self, question: str, tools: list[dict]) -> ExtractedAction:
        tools_block = _build_tools_block(tools)
        prompt = _DYNAMIC_PROMPT.format(question=question, tools_block=tools_block)
        try:
            raw = _to_text(self._llm.invoke(prompt)).strip()
            payload = json.loads(_strip_code_fences(raw))
            if isinstance(payload, list):
                payload = payload[0] if payload else {}
            tool = (payload.get("tool") or "unknown").strip()
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            logger.debug("Dynamic extraction → tool=%s args_keys=%s", tool, list(args.keys()))
            return ExtractedAction(action=tool, params=args)
        except Exception as exc:
            logger.warning("Dynamic extraction failed, trying fallback: %s", exc)
            return self._extract_fallback(question)

    def _extract_fallback(self, question: str) -> ExtractedAction:
        prompt = _FALLBACK_PROMPT.format(question=question)
        try:
            raw = _to_text(self._llm.invoke(prompt)).strip()
            payload = json.loads(_strip_code_fences(raw))
            if isinstance(payload, list):
                payload = payload[0] if payload else {}
            action = (payload.get("action") or "unknown").strip()
            params = payload.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            return ExtractedAction(action=action, params=params)
        except Exception as exc:
            logger.warning("Fallback extraction failed: %s", exc)
            return ExtractedAction(action="unknown", params={})
