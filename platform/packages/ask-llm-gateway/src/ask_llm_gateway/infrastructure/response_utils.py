# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""LLM response normalization helpers.

Centralizes the "what shape does the LLM return content in?" problem so each
consumer doesn't reinvent it. Reasoning models (DeepSeek R1, Claude with
thinking mode, OpenAI o1 via some providers) emit ``response.content`` as a
**list of typed blocks** instead of a plain string — calling ``.strip()`` /
``.startswith()`` directly on that raises ``AttributeError: 'list' object has
no attribute 'strip'``.

Use :func:`content_to_text` whenever you would have done ``response.content``
followed by string operations.
"""

from __future__ import annotations

from typing import Any


def content_to_text(response: Any) -> str:
    """Normalize a LangChain chat response to a plain text string.

    Accepts:
      * Plain LangChain ``BaseMessage`` (``response.content`` is a string)
      * Reasoning-model responses where ``response.content`` is a list of
        typed blocks (``{"type": "reasoning"|"thinking"|"text", ...}``)
      * A bare string
      * Any other object — falls back to ``str(...)``

    Reasoning/thinking blocks are skipped on purpose: callers want the
    user-facing answer, not the chain-of-thought, and parsing reasoning as
    JSON breaks downstream consumers.
    """
    if isinstance(response, str):
        return response

    content = getattr(response, "content", None)
    if content is None:
        return str(response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type", "")
                # Skip reasoning / thinking blocks — they are not the answer.
                if btype in ("thinking", "reasoning", "reasoning_content"):
                    continue
                if "text" in block:
                    parts.append(str(block["text"]))
                elif btype == "text" and "content" in block:
                    parts.append(str(block["content"]))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)
