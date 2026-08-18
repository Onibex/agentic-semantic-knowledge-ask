# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Domain models for the LLM Gateway.
No external dependencies — pure Python dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenUsageRecord:
    """Single LLM call usage record. Tokens only — cost is intentionally not
    tracked: the same model is priced differently per channel (Bedrock / Azure /
    SAP AI Core / direct), so a local estimate would misrepresent the real bill.
    Token counts are the objective, channel-independent signal."""

    phase: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    timestamp_utc: str
    query_id: str | None = None


@dataclass
class LLMConfig:
    """Resolved LLM configuration from settings.json."""

    deployment_id: str
    model_name: str
    embeddings_deployment_id: str = ""

    @classmethod
    def from_settings(cls, settings: dict) -> LLMConfig:
        return cls(
            deployment_id=settings.get("deployments", {}).get("llm", ""),
            model_name=settings.get("model_name", ""),
            embeddings_deployment_id=settings.get("deployments", {}).get("embeddings", ""),
        )
