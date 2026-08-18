# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Embedder factory — module-level companion of `chat_llm_factory.get_chat_llm`.

Centralises the "build an embedder from settings.json" ritual that used to
be reimplemented in 4+ places (each ask-* package's factory + the precise
strategy bootstrap). Reuses `aicore_env.load_aicore_config_from_settings`
which already handles the Windows backslash quirk in `sap_ai_core.config_path`.

Typical use:
    from ask_llm_gateway.application.embedder_factory import get_embedder
    embedder = get_embedder(cfg)        # cfg = parsed settings.json
"""

from __future__ import annotations

from typing import Any

from ..infrastructure.aicore_env import load_aicore_config_from_settings
from ..infrastructure.embedder import SAPAICoreEmbedder


def get_embedder(config: dict[str, Any]) -> SAPAICoreEmbedder:
    """Return a `SAPAICoreEmbedder` for the deployment in `config`.

    Raises ValueError if no embeddings deployment is configured, or
    RuntimeError if the AI Core service-key JSON cannot be located /
    parsed (typically a missing or malformed `sap_ai_core.config_path`).
    """
    deployment_id = (config.get("deployments") or {}).get("embeddings", "")
    if not deployment_id:
        raise ValueError("config.deployments.embeddings is empty — configure it in the Setup page.")
    aicore_cfg = load_aicore_config_from_settings(config)
    if aicore_cfg is None:
        raise RuntimeError("AI Core service-key JSON not found via sap_ai_core.config_path")
    return SAPAICoreEmbedder(deployment_id=deployment_id, aicore_config=aicore_cfg)
