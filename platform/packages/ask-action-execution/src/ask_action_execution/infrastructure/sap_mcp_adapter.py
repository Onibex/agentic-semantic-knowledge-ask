# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
sap_mcp_adapter.py — SAP S/4HANA write operations exposed via MCP.

Implements ``SapActionAdapter`` (domain port). Originally lived under
``chat/sap_s4_service.py``; moved into this package in Iter D-revised so the
ACTION_EXECUTION handler in the orchestrator can talk to a typed package
instead of reaching into ``chat/``.
"""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from .mcp_http_client import mcp_call_sync, mcp_list_tools_sync

logger = logging.getLogger(__name__)

# SAP OData V2/V4: If-Match: * allows PATCH/DELETE without a prior ETag fetch.
_IFMATCH = {"If-Match": "*"}

# Tool name prefix — matches entity set names in api-config.json
_PFX = "A_"


def _to_odata_date(value: str) -> str:
    """Convert an ISO date string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS) to SAP
    OData V2 /Date(milliseconds)/ notation.  Already-formatted values are
    returned unchanged so the function is safe to call twice.
    """
    if not value or value.startswith("/Date("):
        return value
    from datetime import datetime

    dt = datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    ms = int(dt.timestamp() * 1000)
    return f"/Date({ms})/"


# SAP unit code → ISO unit code (both required when specifying a unit)
_SAP_TO_ISO: dict[str, str] = {
    "ST": "PCE",
    "EA": "EA",
    "PC": "PCE",
    "KG": "KGM",
    "G": "GRM",
    "L": "LTR",
    "M": "MTR",
    "M2": "MTK",
    "M3": "MTQ",
    "TO": "TNE",
    "LB": "LBR",
    "FT": "FOT",
    "GAL": "GLL",
    "BOX": "BX",
    "PAL": "PF",
}


def _unit_fields(sap_unit: str) -> dict:
    u = sap_unit.upper()
    return {
        "RequestedQuantitySAPUnit": u,
        "RequestedQuantityISOUnit": _SAP_TO_ISO.get(u, u),
    }


def _pad_order_id(order_id: str) -> str:
    """SAP SalesOrder is stored as 10-digit zero-padded (e.g. 0000006041)."""
    return order_id.zfill(10) if order_id.isdigit() else order_id


def _item_body(
    material: str,
    quantity: float,
    quantity_unit: str | None = None,
    plant: str | None = None,
) -> dict:
    """Build SalesOrderItem body — SalesOrderItem key omitted (SAP auto-assigns).
    SAP requires RequestedQuantitySAPUnit + RequestedQuantityISOUnit — defaults to ST/PCE.
    """
    body: dict = {
        "Material": material,
        "RequestedQuantity": str(quantity),
    }
    body.update(_unit_fields(quantity_unit or "ST"))
    if plant:
        body["Plant"] = plant
    return body


class SapMcpAdapter:
    """SapActionAdapter implementation backed by an MCP server."""

    def __init__(self, mcp_url: str):
        self.mcp_url = mcp_url.rstrip("/")
        self.last_call: dict | None = None

    def _call(self, tool: str, args: dict) -> dict:
        self.last_call = {"tool": tool, "args": args}
        return mcp_call_sync(self.mcp_url, tool, args)

    # ── Tools discovery ───────────────────────────────────────────────────────

    def available_tools(self) -> list[dict]:
        return mcp_list_tools_sync(self.mcp_url)

    # ── Sales Order header ────────────────────────────────────────────────────

    def list_sales_orders(
        self,
        sold_to_party: str | None = None,
        sales_organization: str | None = None,
        sales_order_type: str | None = None,
        top: int = 50,
    ) -> dict:
        query = f"?$top={top}"
        filters = []
        if sold_to_party:
            filters.append(f"SoldToParty eq '{sold_to_party}'")
        if sales_organization:
            filters.append(f"SalesOrganization eq '{sales_organization}'")
        if sales_order_type:
            filters.append(f"SalesOrderType eq '{sales_order_type}'")
        if filters:
            query += "&$filter=" + " and ".join(filters)
        return self._call("A_SalesOrder_list", {"path": query})

    def get_sales_order(self, sales_order_id: str) -> dict:
        return self._call(
            "A_SalesOrder_list",
            {"path": f"?$filter=SalesOrder eq '{sales_order_id}'&$top=1"},
        )

    def get_customer_sales_area(self, sold_to_party: str) -> dict[str, Any] | None:
        """Fetch SalesOrganization, DistributionChannel and Division from A_CustomerSalesArea."""
        try:
            result = self._call(
                "CustomerSalesArea_list",
                {"path": f"?$filter=Customer eq '{sold_to_party}'&$top=1"},
            )
            items = result.get("value", [])
            if items:
                first = items[0]
                return {
                    "sales_organization": first.get("SalesOrganization", ""),
                    "distribution_channel": first.get("DistributionChannel", ""),
                    "organization_division": first.get("Division", ""),
                }
        except Exception:
            pass
        return None

    def create_sales_order(
        self,
        sold_to_party: str,
        sales_order_type: str | None = None,
        sales_organization: str | None = None,
        distribution_channel: str | None = None,
        organization_division: str | None = None,
        requested_delivery_date: str | None = None,
        currency: str | None = None,
        customer_po: str | None = None,
        material: str | None = None,
        quantity: float | None = None,
        quantity_unit: str | None = None,
        plant: str | None = None,
        items: list[dict] | None = None,
    ) -> dict:
        body: dict = {"SoldToParty": sold_to_party}
        if sales_order_type:
            body["SalesOrderType"] = sales_order_type
        if sales_organization:
            body["SalesOrganization"] = sales_organization
        if distribution_channel:
            body["DistributionChannel"] = distribution_channel
        if organization_division:
            body["OrganizationDivision"] = organization_division
        if currency:
            body["TransactionCurrency"] = currency
        if requested_delivery_date:
            body["RequestedDeliveryDate"] = _to_odata_date(requested_delivery_date)
        if customer_po:
            body["PurchaseOrderByCustomer"] = customer_po

        if items:
            body["to_Item"] = [
                _item_body(
                    i["material"], float(i["quantity"]), i.get("quantity_unit"), i.get("plant")
                )
                for i in items
            ]
        elif material and quantity:
            body["to_Item"] = [_item_body(material, float(quantity), quantity_unit, plant)]

        return self._call("A_SalesOrder_create", {"body": body})

    def update_order_header(self, sales_order_id: str, **fields) -> dict:
        if "RequestedDeliveryDate" in fields:
            fields["RequestedDeliveryDate"] = _to_odata_date(fields["RequestedDeliveryDate"])
        return self._call(
            "A_SalesOrder_update",
            {"path": f"('{sales_order_id}')", "body": fields, "headers": _IFMATCH},
        )

    # ── Sales Order items ─────────────────────────────────────────────────────

    def list_order_items(self, sales_order_id: str) -> dict:
        return self._call(
            "A_SalesOrderItem_list",
            {"path": f"?$filter=SalesOrder eq '{sales_order_id}'"},
        )

    def create_order_item(
        self,
        sales_order_id: str,
        material: str,
        quantity: float,
        quantity_unit: str | None = None,
        plant: str | None = None,
    ) -> dict:
        return self._call(
            "A_SalesOrder_create",
            {
                "path": f"('{sales_order_id}')/to_Item",
                "body": _item_body(material, quantity, quantity_unit, plant),
            },
        )

    def update_order_item(self, sales_order_id: str, item_id: str, **fields) -> dict:
        padded = item_id.zfill(6) if item_id.isdigit() else item_id

        # Normalize unit field aliases the LLM might emit — only RequestedQuantitySAPUnit is valid.
        for _alias in ("RequestedQuantityUnit", "OrderQuantityUnit", "QuantityUnit", "Unit"):
            if _alias in fields:
                fields["RequestedQuantitySAPUnit"] = fields.pop(_alias)

        # SAP requires RequestedQuantitySAPUnit + RequestedQuantityISOUnit whenever
        # RequestedQuantity is present. Auto-complete them if the caller omitted them.
        if "RequestedQuantity" in fields:
            fields["RequestedQuantity"] = str(fields["RequestedQuantity"])
            if "RequestedQuantitySAPUnit" not in fields and "RequestedQuantityISOUnit" not in fields:
                # Try to fetch the current unit from SAP; fall back to "ST".
                sap_unit = "ST"
                try:
                    result = self._call(
                        "A_SalesOrderItem_list",
                        {"path": f"?$filter=SalesOrder eq '{sales_order_id}' and SalesOrderItem eq '{padded}'&$top=1"},
                    )
                    items = result.get("value", [])
                    if items:
                        sap_unit = items[0].get("RequestedQuantitySAPUnit") or items[0].get("OrderQuantityUnit") or "ST"
                except Exception:
                    pass
                fields.update(_unit_fields(sap_unit))

        # Convert date fields to OData /Date()/ notation if present.
        if "RequestedDeliveryDate" in fields:
            fields["RequestedDeliveryDate"] = _to_odata_date(fields["RequestedDeliveryDate"])

        return self._call(
            "A_SalesOrderItem_update",
            {
                "path": f"(SalesOrder='{_pad_order_id(sales_order_id)}',SalesOrderItem='{padded}')",
                "body": fields,
                "headers": _IFMATCH,
            },
        )

    def delete_order_item(self, sales_order_id: str, item_id: str) -> dict:
        padded_order = _pad_order_id(sales_order_id)
        padded_item = item_id.zfill(6) if item_id.isdigit() else item_id
        return self._call(
            "A_SalesOrderItem_delete",
            {
                "path": f"(SalesOrder='{padded_order}',SalesOrderItem='{padded_item}')",
                "headers": _IFMATCH,
            },
        )

    # ── Partners ──────────────────────────────────────────────────────────────

    def list_order_partners(self, sales_order_id: str) -> dict:
        return self._call(
            "A_SalesOrderPartner_list",
            {"path": f"?$filter=SalesOrder eq '{sales_order_id}'"},
        )

    def list_item_partners(self, sales_order_id: str, item_id: str | None = None) -> dict:
        path = f"?$filter=SalesOrder eq '{sales_order_id}'"
        if item_id:
            padded = item_id.zfill(6) if item_id.isdigit() else item_id
            path += f" and SalesOrderItem eq '{padded}'"
        return self._call("A_SalesOrderItemPartner_list", {"path": path})

    # ── Pricing ───────────────────────────────────────────────────────────────

    def list_order_pricing(self, sales_order_id: str) -> dict:
        return self._call(
            "A_SalesOrderHeaderPrElement_list",
            {"path": f"?$filter=SalesOrder eq '{sales_order_id}'"},
        )

    def list_item_pricing(self, sales_order_id: str, item_id: str | None = None) -> dict:
        path = f"?$filter=SalesOrder eq '{sales_order_id}'"
        if item_id:
            padded = item_id.zfill(6) if item_id.isdigit() else item_id
            path += f" and SalesOrderItem eq '{padded}'"
        return self._call("A_SalesOrderItemPrElement_list", {"path": path})

    # ── Texts ─────────────────────────────────────────────────────────────────

    def list_order_texts(self, sales_order_id: str) -> dict:
        return self._call(
            "A_SalesOrderText_list",
            {"path": f"?$filter=SalesOrder eq '{sales_order_id}'"},
        )

    def list_item_texts(self, sales_order_id: str, item_id: str | None = None) -> dict:
        path = f"?$filter=SalesOrder eq '{sales_order_id}'"
        if item_id:
            padded = item_id.zfill(6) if item_id.isdigit() else item_id
            path += f" and SalesOrderItem eq '{padded}'"
        return self._call("A_SalesOrderItemText_list", {"path": path})

    # ── Schedule lines ────────────────────────────────────────────────────────

    def list_schedule_lines(self, sales_order_id: str, item_id: str | None = None) -> dict:
        path = f"?$filter=SalesOrder eq '{sales_order_id}'"
        if item_id:
            padded = item_id.zfill(6) if item_id.isdigit() else item_id
            path += f" and SalesOrderItem eq '{padded}'"
        return self._call("A_SalesOrderScheduleLine_list", {"path": path})

    # ── Health check ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        try:
            import asyncio

            import aiohttp

            async def _ping():
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        self.mcp_url.replace("/mcp", "") + "/health",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as r:
                        return r.status == 200

            return asyncio.run(_ping())
        except Exception:
            return False
