"""
ask-llm-gateway — Multi-provider LLM + Embedder backbone for the ASK Platform.

Public API (everything a consumer needs):
    from ask_llm_gateway import build_llm, build_embedder   # canonical multi-provider API
    from ask_llm_gateway import TokenTracker, set_active_tracker, track_phase

Internal structure follows Hexagonal Architecture:
    domain/        — pure models and port protocols
    application/   — factories: build_llm, build_embedder (+ sap_aicore-specific aliases)
    infrastructure/ — two backends: native SAP AI Core (gen_ai_hub) + LiteLLM
                      (ChatLiteLLM / litellm.embedding) covering Bedrock, Azure,
                      OpenAI, Anthropic, Vertex/Gemini and 100+ providers — plus
                      local sentence-transformers embeddings and the token tracker.
"""

# ── Canonical multi-provider factories (preferred by all consumers) ──────────
# ── SAP AI Core aliases kept for backward compatibility ──────────────────────
from .application.chat_llm_factory import get_chat_llm
from .application.embedder_factory import get_embedder
from .application.factory import build_embedder, build_llm, get_provider_display

# ── Domain models ────────────────────────────────────────────────────────────
from .domain.models import LLMConfig, TokenUsageRecord
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
    # SAP AI Core aliases (backward compat)
    "get_chat_llm",
    "get_embedder",
    # Domain models
    "LLMConfig",
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
