"""
ActionExecutionApplicationService — orchestrates the ACTION_EXECUTION flow.

Pipeline per request:
  1. Run the ``LlmActionExtractor`` to obtain ``{action, params}``.
  2. Dispatch to the appropriate ``SapActionAdapter`` method, defaulting
     missing fields where possible (e.g. fetching the customer sales area
     from SAP when the user did not provide it).
  3. Translate the SAP raw result into a business-friendly natural-language
     ``answer`` via the LLM formatter.

The UI never sees an LLM client or an MCP adapter — it just receives
``ActionResponse.answer`` over REST.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..domain.models import ActionRequest, ActionResponse
from ..domain.ports import ActionExtractorPort, SapActionAdapter

logger = logging.getLogger(__name__)


_NOT_CONFIGURED_ANSWER = (
    "SAP S/4HANA is not configured. Please go to the Configuration App → "
    "SAP S/4HANA to set up the MCP endpoint."
)

_UNKNOWN_ACTION_ANSWER = (
    "I can only create, update, or delete records via the SAP API. "
    "For queries and reports, please ask directly and I'll look it up from the database."
)

# Actions handled by the legacy named-dispatch path.
_LEGACY_ACTIONS = frozenset(
    {"create_order", "update_header", "create_item", "update_item", "delete_item"}
)


def _format_error_prompt(question: str, error_detail: str) -> str:
    return f"""The user asked: {question}

SAP S/4HANA returned this error:
{error_detail[:2000]}

Explain what went wrong in plain business language. Be specific about which field is invalid if you can detect it from the error text.
Do NOT suggest OAuth or token URL issues — the connection itself works fine.
If the error mentions an invalid order type or sales area, say so clearly and suggest the correct values if you can infer them."""


def _format_success_prompt(question: str, raw_result: dict) -> str:
    return f"""The user asked: {question}

SAP S/4HANA returned this data:
{json.dumps(raw_result, indent=2, default=str)[:3000]}

Summarize the result in a clear, business-friendly response. Use markdown tables if there are multiple records."""


class ActionExecutionApplicationService:
    """Default implementation of ``ActionExecutionService``."""

    def __init__(
        self,
        extractor: ActionExtractorPort,
        adapter: SapActionAdapter | None,
        llm: Any,
    ):
        self._extractor = extractor
        self._adapter = adapter
        self._llm = llm

    def execute(self, request: ActionRequest) -> ActionResponse:
        if self._adapter is None:
            return ActionResponse(
                answer=_NOT_CONFIGURED_ANSWER,
                success=False,
                error="adapter_not_configured",
            )

        extracted = self._extractor.extract(request.question)
        action = extracted.action
        params = dict(extracted.params)
        logger.info(
            "ACTION_EXECUTION extracted: action=%s params=%s",
            action,
            json.dumps(params, default=str)[:1000],
        )

        try:
            result = self._dispatch(action, params)
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.exception("ACTION_EXECUTION dispatch failed")
            return ActionResponse(
                answer=f"Pipeline error: {exc}",
                action=action,
                success=False,
                error=str(exc),
            )

        return self._build_response(request.question, action, result)

    # ── Dispatch ─────────────────────────────────────────────────────────────

    def _dispatch(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        # A_SalesOrderItem_delete / _update from the dynamic extractor:
        # extract order+item IDs from Nova Pro's path predicate and route to
        # the legacy dispatch which normalizes zero-padding via the adapter.
        if action in ("A_SalesOrderItem_delete", "A_SalesOrderItem_update"):
            path = params.get("path") or ""
            m_order = re.search(r"SalesOrder='([^']*)'", path)
            m_item = re.search(r"SalesOrderItem='([^']*)'", path)
            # Fall back to root-level args when Nova Pro skips the path format.
            order_id = (
                (m_order.group(1) if m_order else None)
                or params.get("SalesOrder")
                or params.get("sales_order_id")
                or ""
            )
            item_id = (
                (m_item.group(1) if m_item else None)
                or params.get("SalesOrderItem")
                or params.get("item_id")
                or ""
            )
            if action == "A_SalesOrderItem_delete":
                return self._dispatch_delete_item(
                    {"sales_order_id": str(order_id), "item_id": str(item_id)}
                )
            body = params.get("body") or {}
            return self._dispatch_update_item(
                {"sales_order_id": str(order_id), "item_id": str(item_id), **body}
            )

        # A_SalesOrder_create from the dynamic extractor: bridge to the legacy
        # path which handles SAP field names, unit fields, and to_Item correctly.
        if action == "A_SalesOrder_create":
            body = params.get("body") or {}
            legacy: dict[str, Any] = {
                "sold_to_party": body.get("SoldToParty") or body.get("Customer") or "",
                "sales_order_type": body.get("SalesOrderType") or "",
                "sales_organization": body.get("SalesOrganization") or "",
                "distribution_channel": body.get("DistributionChannel") or "",
                "organization_division": body.get("OrganizationDivision") or "",
                "customer_po": body.get("PurchaseOrderByCustomer") or body.get("CustomerPO") or "",
                "requested_delivery_date": body.get("RequestedDeliveryDate") or "",
            }
            raw_items = body.get("to_Item") or []
            if raw_items:
                # Nova Pro returns PascalCase OData keys; normalize to snake_case
                # so _dispatch_create_order → adapter._item_body can consume them.
                legacy["items"] = [
                    {
                        "material": it.get("Material") or it.get("material") or "",
                        "quantity": it.get("RequestedQuantity") or it.get("quantity") or 1,
                        "quantity_unit": it.get("RequestedQuantitySAPUnit")
                        or it.get("quantity_unit"),
                        "plant": it.get("Plant") or it.get("plant"),
                    }
                    for it in raw_items
                ]
            return self._dispatch_create_order(legacy)

        # A_ProductionOrder_2_create: normalize field names to actual OData names.
        # The LLM may use OrderType/MRPPlant/Quantity; SAP requires
        # ManufacturingOrderType/ProductionPlant/TotalQuantity.
        if action == "A_ProductionOrder_2_create":
            body = params.get("body") or {}
            normalized: dict[str, Any] = {}
            normalized["ManufacturingOrderType"] = (
                body.get("ManufacturingOrderType")
                or body.get("OrderType")
                or body.get("ManufacturingOrderTypeCode")
                or ""
            )
            normalized["Material"] = body.get("Material") or ""
            normalized["ProductionPlant"] = (
                body.get("ProductionPlant") or body.get("MRPPlant") or body.get("Plant") or ""
            )
            qty = body.get("TotalQuantity") or body.get("Quantity") or body.get("quantity") or ""
            if qty:
                normalized["TotalQuantity"] = str(qty)
            unit = body.get("ProductionUnit") or body.get("Unit") or body.get("unit") or ""
            if unit:
                normalized["ProductionUnit"] = unit
            # Pass through any other fields the LLM provided, converting dates.
            _handled = {
                "ManufacturingOrderType",
                "OrderType",
                "ManufacturingOrderTypeCode",
                "Material",
                "ProductionPlant",
                "MRPPlant",
                "Plant",
                "TotalQuantity",
                "Quantity",
                "quantity",
                "ProductionUnit",
                "Unit",
                "unit",
            }
            _date_fields = {
                "MfgOrderPlannedEndDate",
                "MfgOrderPlannedStartDate",
                "MfgOrderScheduledEndDate",
                "MfgOrderScheduledStartDate",
                "BasicFinishDate",
                "BasicStartDate",
            }
            from ..infrastructure.sap_mcp_adapter import _to_odata_date

            for k, v in body.items():
                if k in _handled:
                    continue
                normalized[k] = _to_odata_date(str(v)) if k in _date_fields else v
            # Drop empty strings so SAP uses its own defaults
            clean = {k: v for k, v in normalized.items() if v != ""}
            logger.info(
                "Production order bridge: normalized body=%s",
                {k: v for k, v in clean.items() if k != "ManufacturingOrderType"}
                | {"ManufacturingOrderType": clean.get("ManufacturingOrderType")},
            )
            return self._dispatch_direct_tool(action, {"body": clean})

        # Dynamic MCP dispatch — when the extractor returned a live tool name
        # (e.g. A_ProductionOrder_2_list) instead of a legacy named action,
        # call the MCP server directly.
        if action not in _LEGACY_ACTIONS and action != "unknown" and "_" in action:
            return self._dispatch_direct_tool(action, params)

        if action == "create_order":
            return self._dispatch_create_order(params)
        if action == "update_header":
            return self._dispatch_update_header(params)
        if action == "create_item":
            return self._dispatch_create_item(params)
        if action == "update_item":
            return self._dispatch_update_item(params)
        if action == "delete_item":
            return self._dispatch_delete_item(params)
        return {"_missing": _UNKNOWN_ACTION_ANSWER}

    def _dispatch_direct_tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call an arbitrary MCP tool by name — used for contract-driven dispatch."""
        assert self._adapter is not None  # narrowed in execute()
        try:
            result = self._adapter._call(tool, args)  # type: ignore[union-attr]
            logger.info(
                "Direct tool result: tool=%s result=%s",
                tool,
                json.dumps(result, default=str)[:2000],
            )
            return result
        except Exception as exc:
            logger.exception("Direct MCP tool call failed: tool=%s", tool)
            return {"error": str(exc)}

    def _dispatch_create_order(self, params: dict[str, Any]) -> dict[str, Any]:
        sold_to = (params.get("sold_to_party") or "").strip()
        if not sold_to:
            return {
                "_missing": (
                    "To create a Sales Order I need the customer number.\n"
                    "- **Sold-To Party** (customer number, e.g. `CUST-1000`) — *required*\n"
                    "- Requested Delivery Date (optional, e.g. `2026-06-30`)\n"
                    "- Line items: material, quantity, unit (optional)\n\n"
                    "Sales area defaults (Org, DC, Division) will be fetched automatically from SAP."
                )
            }

        # Filter to known kwargs (defensive — LLM may invent extras).
        allowed = {
            "sold_to_party",
            "sales_order_type",
            "sales_organization",
            "distribution_channel",
            "organization_division",
            "requested_delivery_date",
            "currency",
            "customer_po",
            "material",
            "quantity",
            "quantity_unit",
            "plant",
        }
        create_kwargs = {k: v for k, v in params.items() if k in allowed}

        # Auto-resolve sales area from SAP when missing.
        if not create_kwargs.get("sales_organization"):
            assert self._adapter is not None  # narrowed in execute()
            sap_defaults = self._adapter.get_customer_sales_area(sold_to)
            if sap_defaults:
                create_kwargs.setdefault(
                    "sales_organization", sap_defaults.get("sales_organization")
                )
                create_kwargs.setdefault(
                    "distribution_channel", sap_defaults.get("distribution_channel")
                )
                create_kwargs.setdefault(
                    "organization_division", sap_defaults.get("organization_division")
                )
            else:
                return {
                    "_missing": (
                        f"I need the sales area for customer **{sold_to}** to create the order.\n"
                        "Please provide:\n"
                        "- **Sales Organization** (e.g. `1010`)\n"
                        "- **Distribution Channel** (e.g. `10`)\n"
                        "- **Division** (e.g. `00`)\n\n"
                        "These will be looked up automatically from SAP once the Business Partner "
                        "API contract is configured in the Contracts page."
                    )
                }

        raw_items = params.get("items") or []
        if raw_items:
            create_kwargs["items"] = raw_items

        logger.info("create_sales_order kwargs=%s", json.dumps(create_kwargs, default=str))
        assert self._adapter is not None
        return self._adapter.create_sales_order(**create_kwargs)

    def _dispatch_update_header(self, params: dict[str, Any]) -> dict[str, Any]:
        order_id = (params.get("sales_order_id") or "").strip()
        if not order_id:
            return {"_missing": "Please provide the Sales Order number you want to update."}
        fields = {k: v for k, v in params.items() if k != "sales_order_id"}
        if not fields:
            return {
                "_missing": "Please specify which fields to update (e.g. RequestedDeliveryDate, PurchaseOrderByCustomer)."
            }
        assert self._adapter is not None
        return self._adapter.update_order_header(order_id, **fields)

    def _dispatch_create_item(self, params: dict[str, Any]) -> dict[str, Any]:
        order_id = (params.get("sales_order_id") or "").strip()
        material = (params.get("material") or "").strip()
        quantity = params.get("quantity", 0)
        if not order_id or not material or not quantity:
            return {
                "_missing": (
                    "To add a line item I need:\n"
                    "- **Sales Order number** (e.g. `6037`)\n"
                    "- **Material / Product** (e.g. `TG12`)\n"
                    "- **Quantity** (e.g. `10`)\n\n"
                    "Please provide the missing values."
                )
            }
        assert self._adapter is not None
        return self._adapter.create_order_item(
            sales_order_id=order_id,
            material=material,
            quantity=float(quantity),
            quantity_unit=params.get("quantity_unit") or None,
            plant=params.get("plant"),
        )

    def _dispatch_update_item(self, params: dict[str, Any]) -> dict[str, Any]:
        order_id = (params.get("sales_order_id") or "").strip()
        item_id = str(params.get("item_id") or "").strip()

        # If item_id is missing but material is provided, look up the item by material.
        if not item_id and order_id and params.get("material"):
            assert self._adapter is not None
            try:
                result = self._adapter.list_order_items(order_id)
                items = result.get("value", [])
                material_upper = str(params["material"]).upper()
                for it in items:
                    if str(it.get("Material", "")).upper() == material_upper:
                        item_id = str(it.get("SalesOrderItem", "")).lstrip("0") or str(
                            it.get("SalesOrderItem", "")
                        )
                        break
            except Exception:
                pass

        if not order_id or not item_id:
            return {
                "_missing": "Please provide both the Sales Order number and the Item number (or material) to update."
            }
        fields = {
            k: v for k, v in params.items() if k not in ("sales_order_id", "item_id", "material")
        }
        assert self._adapter is not None
        return self._adapter.update_order_item(order_id, item_id, **fields)

    def _dispatch_delete_item(self, params: dict[str, Any]) -> dict[str, Any]:
        order_id = (params.get("sales_order_id") or "").strip()
        item_id = str(params.get("item_id") or "").strip()
        if not order_id or not item_id:
            return {
                "_missing": "Please provide both the Sales Order number and the Item number to delete."
            }
        assert self._adapter is not None
        return self._adapter.delete_order_item(order_id, item_id)

    # ── Response building ────────────────────────────────────────────────────

    def _build_response(
        self,
        question: str,
        action: str,
        result: dict[str, Any],
    ) -> ActionResponse:
        logger.info(
            "ACTION_EXECUTION result: action=%s result=%s",
            action,
            json.dumps(result, default=str)[:2000],
        )
        if "_missing" in result:
            return ActionResponse(
                answer=result["_missing"],
                action=action,
                success=False,
            )
        if "error" in result:
            answer = self._llm_format(_format_error_prompt(question, str(result["error"])))
            return ActionResponse(
                answer=answer,
                action=action,
                success=False,
                error=str(result["error"]),
                raw_result=result,
            )
        answer = self._llm_format(_format_success_prompt(question, result))
        return ActionResponse(
            answer=answer,
            action=action,
            success=True,
            raw_result=result,
        )

    def _llm_format(self, prompt: str) -> str:
        try:
            response = self._llm.invoke(prompt)
            # LangChain AIMessage has .content; plain string passthrough; fallback str().
            if isinstance(response, str):
                return response
            content = getattr(response, "content", None)
            return content if isinstance(content, str) else str(response)
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning("LLM formatter failed: %s", exc)
            return "(SAP request completed, but the answer formatter failed.)"
