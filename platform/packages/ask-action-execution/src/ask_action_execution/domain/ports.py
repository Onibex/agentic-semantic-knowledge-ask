# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Inbound / outbound ports for the Action Execution service."""

from __future__ import annotations

from typing import Any, Protocol

from .models import ActionRequest, ActionResponse, ExtractedAction


class ActionExecutionService(Protocol):
    """Inbound port — the orchestrator-facing contract for ACTION_EXECUTION."""

    def execute(self, request: ActionRequest) -> ActionResponse: ...


class ActionExtractorPort(Protocol):
    """Outbound port — extracts a structured action+params from natural language."""

    def extract(self, question: str) -> ExtractedAction: ...


class SapActionAdapter(Protocol):
    """Outbound port — write operations against SAP S/4HANA (via MCP).

    Mirrors the surface of the MCP-backed ``SAPS4Service`` so future adapters
    (REST/OData direct, mock for tests) can stand in.
    """

    def get_customer_sales_area(self, customer_id: str) -> dict[str, Any] | None: ...

    def create_sales_order(self, **kwargs: Any) -> dict[str, Any]: ...

    def update_order_header(self, sales_order_id: str, **fields: Any) -> dict[str, Any]: ...

    def create_order_item(
        self,
        sales_order_id: str,
        material: str,
        quantity: float,
        quantity_unit: str | None = None,
        plant: str | None = None,
    ) -> dict[str, Any]: ...

    def update_order_item(
        self, sales_order_id: str, item_id: str, **fields: Any
    ) -> dict[str, Any]: ...

    def delete_order_item(self, sales_order_id: str, item_id: str) -> dict[str, Any]: ...
