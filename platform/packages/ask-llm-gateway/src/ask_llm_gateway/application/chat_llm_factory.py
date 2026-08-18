# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
utils/llm_factory.py

LLM factory — all models run as SAP AI Core deployments via gen_ai_hub.

Model routing (based on model_name prefix):
  anthropic--*  → ChatBedrockConverse (Bedrock Converse API — works for all Claude versions)
  amazon--*     → ChatBedrockConverse
  default       → ChatOpenAI proxy (GPT-4o, GPT-4-turbo, etc.)

Token tracking:
  Every returned LLM is pre-configured with `AutoTrackingCallback(model_name)`.
  If a `TokenTracker` has been published to the contextvar via
  `set_active_tracker(...)`, every `.invoke()` / chain call will be recorded
  automatically. See `src/shared/token_tracker.py`.
"""

from __future__ import annotations

from typing import Any

# Token tracker is part of the legacy pipelines (legacy/src/shared/...). The
# slim chat image (Iter 1, T12) ships without legacy/, so this import has to
# fail gracefully — instrumentation is "best-effort" and absence is harmless.
try:
    from ask_llm_gateway.infrastructure.token_tracker import (
        AutoTrackingCallback,  # type: ignore[import-not-found]
    )

    _TOKEN_TRACKER_AVAILABLE = True
except ImportError:
    _TOKEN_TRACKER_AVAILABLE = False


def _is_bedrock_model(model_name: str) -> bool:
    return model_name.startswith("anthropic--") or model_name.startswith("amazon--")


def _auto_tracking_callbacks(model_name: str) -> list[Any]:
    """Build the default callback list attached to every LLM instance.

    Returns an empty list when the token tracker module is not on PYTHONPATH
    (the Iter 1 slim chat image).
    """
    if not _TOKEN_TRACKER_AVAILABLE:
        return []
    return [AutoTrackingCallback(model=model_name or "unknown")]


def _get_model_name_from_deployment(deployment_id: str) -> str:
    """Resolve model_name from AI Core deployment list."""
    try:
        from gen_ai_hub.proxy.core.proxy_clients import get_proxy_client

        client = get_proxy_client("gen-ai-hub")
        for dep in client.get_deployments():
            if dep.deployment_id == deployment_id:
                return dep.model_name
    except Exception:
        pass
    return ""


def get_chat_llm(config: dict[str, Any]):
    """
    Return a LangChain chat model for the configured SAP AI Core deployment.

    Detects model family from config["model_name"] (set by Setup).
    Falls back to querying AI Core if model_name is missing.
    """
    deployment_id = config.get("deployments", {}).get("llm", "")
    if not deployment_id:
        raise ValueError(
            "No LLM deployment ID configured. Please go to Setup and select a deployment."
        )

    # Boot AICORE_* env vars from the on-disk service key when available.
    # Kyma injects them via Secret instead, so a missing JSON is OK there.
    from ask_llm_gateway.infrastructure.aicore_env import ensure_aicore_env_from_settings

    ensure_aicore_env_from_settings(config)

    model_name = config.get("model_name", "") or _get_model_name_from_deployment(deployment_id)

    if _is_bedrock_model(model_name):
        # Claude and Amazon models in AI Core go through Bedrock Converse API.
        # The SDK's MODEL_NAME_TO_MODEL_ID_MAP only covers up to claude-3.7.
        # Patch it at runtime so newer models (claude-4.x) pass validation.
        # AI Core routes by deployment_id server-side, so the model_id value
        # only needs to be a non-empty string — the actual model used is
        # determined by the deployment, not by this field.
        from gen_ai_hub.proxy.langchain.amazon import (
            MODEL_NAME_TO_MODEL_ID_MAP,
            ChatBedrockConverse,
        )

        if model_name not in MODEL_NAME_TO_MODEL_ID_MAP:
            # Use the latest known Claude converse model_id as a placeholder.
            # AI Core ignores this value and routes via deployment_id instead.
            MODEL_NAME_TO_MODEL_ID_MAP[model_name] = "anthropic.claude-3-7-sonnet-20250219-v1:0"

        from langchain_core.messages import BaseMessage
        from langchain_core.outputs import ChatResult

        class _BedrockNoStop(ChatBedrockConverse):
            def _generate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                **kwargs: Any,
            ) -> ChatResult:
                return super()._generate(messages, stop=None, **kwargs)

        # Output-token ceiling (configurable). 4096 truncated complex multi-CTE
        # SQL mid-string; a ceiling costs nothing extra for short answers.
        _max_tokens = int(config.get("llm_max_tokens") or 8192)
        return _BedrockNoStop(
            deployment_id=deployment_id,
            model_name=model_name,
            model_kwargs={"temperature": 0, "max_tokens": _max_tokens},
            callbacks=_auto_tracking_callbacks(model_name),
        )

    # Default: OpenAI-compatible models (GPT-4o, etc.)

    from gen_ai_hub.proxy.langchain.openai import ChatOpenAI as SAPChatOpenAI
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import ChatResult

    class _OpenAINoStop(SAPChatOpenAI):
        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            **kwargs: Any,
        ) -> ChatResult:
            return super()._generate(messages, stop=None, **kwargs)

        def _stream(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            **kwargs: Any,
        ):
            return super()._stream(messages, stop=None, **kwargs)

    init_kwargs: dict[str, Any] = {
        "deployment_id": deployment_id,
        "temperature": 0,
        "callbacks": _auto_tracking_callbacks(model_name),
    }
    # Pass model_name so the request body uses the correct model field.
    # Some SAP-native models (e.g. sap--rpt-large) return 404 when the
    # model field defaults to "gpt-3.5-turbo" instead of the actual model.
    if model_name:
        init_kwargs["model_name"] = model_name
    return _OpenAINoStop(**init_kwargs)


def get_provider_display(config: dict[str, Any]) -> str:
    """Return a human-readable label for the current deployment."""
    deployment_id = config.get("deployments", {}).get("llm", "")
    model_name = config.get("model_name", "")
    label = model_name or deployment_id[:25]
    return f"SAP AI Core · {label}"
