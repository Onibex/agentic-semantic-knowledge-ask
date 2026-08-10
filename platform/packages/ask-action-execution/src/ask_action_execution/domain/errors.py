"""Errors raised by the Action Execution Service."""

from __future__ import annotations


class ActionExecutionError(Exception):
    """Base error."""


class AdapterNotConfiguredError(ActionExecutionError):
    """Raised when the SAP S/4HANA MCP adapter is not configured (no mcp_url)."""


class ActionExtractionError(ActionExecutionError):
    """Raised when the LLM extractor fails to produce a usable action+params."""
