# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Ports for SQL Generation.

Inbound:
  - SqlGenerator: the contract the orchestrator depends on. Concrete impl is
    application.freeform_generator.FreeformSQLGenerator.

Outbound (stub for Iter 4):
  - LLMPort: declared so future consumers can mock without binding to
    langchain. The Iter 3 implementation calls langchain LLMs directly via
    utils.llm_factory; promotion to a real LLMPort happens once
    ask-llm-gateway is unblocked.
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import SqlGenerationRequest, SqlGenerationResult


class SqlGenerator(Protocol):
    """The single inbound contract."""

    def generate(self, request: SqlGenerationRequest) -> SqlGenerationResult: ...


class LLMPort(Protocol):
    """Outbound — Iter 4 will use this when ask-llm-gateway is consumable."""

    def chat(self, prompt: str, **kwargs: Any) -> str: ...
