# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Errors raised by the Action Execution Service."""

from __future__ import annotations


class ActionExecutionError(Exception):
    """Base error."""


class AdapterNotConfiguredError(ActionExecutionError):
    """Raised when the SAP S/4HANA MCP adapter is not configured (no mcp_url)."""


class ActionExtractionError(ActionExecutionError):
    """Raised when the LLM extractor fails to produce a usable action+params."""
