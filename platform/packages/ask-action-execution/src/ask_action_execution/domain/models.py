"""Domain models for ACTION_EXECUTION (SAP write operations via MCP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionRequest:
    """Inbound request — natural-language description of the desired SAP action."""

    question: str
    user_id: str | None = None  # for audit / RBAC (Iter 7+)


@dataclass(frozen=True)
class ExtractedAction:
    """Result of running the LLM extractor on `question`."""

    action: str  # create_order | update_header | create_item | update_item | delete_item | unknown
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionResponse:
    """Outcome of one ACTION_EXECUTION request.

    `answer` is always populated and is what the UI renders. The remaining
    fields are diagnostic and may be consumed by Watsonx / MCP audit later.
    """

    answer: str
    action: str | None = None
    success: bool = False
    raw_result: dict[str, Any] | None = None
    error: str | None = None
