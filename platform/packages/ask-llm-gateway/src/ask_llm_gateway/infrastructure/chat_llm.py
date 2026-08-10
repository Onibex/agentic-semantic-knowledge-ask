"""
SAP AI Core chat LLM factory.

Supports:
  anthropic--* / amazon--*  → ChatBedrockConverse
  everything else           → ChatOpenAI proxy (SAP gen_ai_hub)

Token tracking is wired via AutoTrackingCallback — see token_tracker.py.
"""

from __future__ import annotations

from typing import Any


def _is_bedrock_model(model_name: str) -> bool:
    return model_name.startswith("anthropic--") or model_name.startswith("amazon--")


def _resolve_model_name(deployment_id: str) -> str:
    """Query SAP AI Core to resolve model_name from deployment_id."""
    try:
        from gen_ai_hub.proxy.core.proxy_clients import get_proxy_client

        client = get_proxy_client("gen-ai-hub")
        for dep in client.get_deployments():
            if dep.deployment_id == deployment_id:
                return dep.model_name
    except Exception:
        pass
    return ""


def build_chat_llm(config: dict[str, Any]):
    """
    Return a LangChain chat model for the configured SAP AI Core deployment.
    Attaches AutoTrackingCallback for transparent token accounting.
    """
    deployment_id = config.get("deployments", {}).get("llm", "")
    if not deployment_id:
        raise ValueError("No LLM deployment ID configured. Go to Setup and select a deployment.")

    model_name = config.get("model_name", "") or _resolve_model_name(deployment_id)

    from .token_tracker import AutoTrackingCallback

    callbacks = [AutoTrackingCallback(model=model_name)]

    if _is_bedrock_model(model_name):
        from gen_ai_hub.proxy.langchain.amazon import (
            MODEL_NAME_TO_MODEL_ID_MAP,
            ChatBedrockConverse,
        )

        # Patch map so newer Claude 4.x models pass SDK validation.
        # AI Core routes by deployment_id server-side; this value is a placeholder.
        if model_name not in MODEL_NAME_TO_MODEL_ID_MAP:
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

        return _BedrockNoStop(
            deployment_id=deployment_id,
            model_name=model_name,
            model_kwargs={"temperature": 0, "max_tokens": 8192},
            callbacks=callbacks,
        )

    # Default: OpenAI-compatible (GPT-4o, GPT-4-turbo, SAP-native models)
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
        "callbacks": callbacks,
    }
    if model_name:
        init_kwargs["model_name"] = model_name
    return _OpenAINoStop(**init_kwargs)


def get_provider_display(config: dict[str, Any]) -> str:
    """Human-readable label for the current LLM deployment."""
    deployment_id = config.get("deployments", {}).get("llm", "")
    model_name = config.get("model_name", "")
    label = model_name or deployment_id[:25]
    return f"SAP AI Core · {label}"
