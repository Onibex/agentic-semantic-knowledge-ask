# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask-llm-gateway — Multi-provider LLM + Embedder backbone for the ASK Platform.

Public API (everything a consumer needs):
    from ask_llm_gateway import build_llm, build_embedder   # canonical multi-provider API
    from ask_llm_gateway import TokenTracker, set_active_tracker, track_phase

Internal structure follows Hexagonal Architecture:
    domain/        — pure models and port protocols
    application/   — factories: build_llm, build_embedder
    infrastructure/ — LiteLLM (ChatLiteLLM / litellm.embedding) covering Bedrock,
                      Azure, OpenAI, Anthropic, Vertex/Gemini, SAP AI Core and
                      100+ providers, plus local sentence-transformers
                      embeddings and the token tracker.
"""

# ── Canonical multi-provider factories (preferred by all consumers) ──────────
from .application.factory import build_embedder, build_llm, get_provider_display

# ── Domain models ────────────────────────────────────────────────────────────
from .domain.models import TokenUsageRecord
from .domain.ports import ChatLLMPort, EmbedderPort, TokenTrackerPort

# ── Token tracking (used directly by orchestrator and strategies) ─────────────
from .infrastructure.token_tracker import (
    TokenTracker,
    clear_active_tracker,
    get_active_tracker,
    set_active_tracker,
    track_phase,
)

__all__ = [
    # Canonical multi-provider factories
    "build_llm",
    "build_embedder",
    "get_provider_display",
    # Domain models
    "TokenUsageRecord",
    # Ports (for type hints in consumers)
    "ChatLLMPort",
    "EmbedderPort",
    "TokenTrackerPort",
    # Token tracking helpers (used directly by services)
    "TokenTracker",
    "set_active_tracker",
    "get_active_tracker",
    "clear_active_tracker",
    "track_phase",
]
