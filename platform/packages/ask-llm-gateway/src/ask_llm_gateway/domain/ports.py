# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Inbound and outbound ports for the LLM Gateway.

Inbound (what consumers call):
  LLMGatewayPort — the public interface of this package.

These protocols are what the rest of the system depends on.
Concrete implementations live in infrastructure/.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import TokenUsageRecord


@runtime_checkable
class ChatLLMPort(Protocol):
    """Minimal interface expected from a LangChain chat model."""

    def invoke(self, input: Any, **kwargs: Any) -> Any: ...
    def stream(self, input: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class EmbedderPort(Protocol):
    """Minimal interface expected from an embedding model."""

    def embed_query(self, text: str) -> list[float]: ...
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class TokenTrackerPort(Protocol):
    """Interface for recording LLM usage during a query."""

    def record(
        self,
        *,
        phase: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> TokenUsageRecord: ...

    def summary(self) -> dict[str, Any]: ...
    def reset(self) -> None: ...
