# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ProfileBuilder — LLM synthesis of a user's analytics profile from chat history.

The prompt + parsing live server-side so no UI ever needs an LLM client: the
chat SPA posts the history to ``/v1/profile`` and gets a structured
``ProfileBuildResponse`` back. Persisting the result is the caller's concern.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ask_llm_gateway.infrastructure.response_utils import content_to_text

from ..models.profile import ProfileBuildResponse

logger = logging.getLogger(__name__)


_PROFILE_PROMPT = """\
You are analyzing a user's conversation history with a business data analytics chatbot \
(connected to SAP HANA) to build their professional profile.

Based on the following conversation history, extract information for each category. \
Be concise and factual. Only include information that is clearly evident from the \
conversations. Respond in the same language the user uses in their conversations.

User Role: {role}
User Name: {display_name}

Recent conversations:
{conversations}

Return a JSON object with exactly these keys:
{{
  "work_context": "What SAP modules, business processes, database tables, or business domains does this user work with? (2-3 sentences)",
  "personal_context": "What is their apparent role or responsibility based on the questions they ask? (1-2 sentences)",
  "top_of_mind": ["3-5 short bullet points of current topics or questions they seem focused on"],
  "brief_history": "Overall summary of what this user has been working on across all their conversations (2-3 sentences)",
  "recent_months": "What have they been focused on most recently based on their latest chats? (2-3 sentences)"
}}

Return ONLY valid JSON, no markdown, no explanation.\
"""


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text


def _empty_profile() -> dict[str, Any]:
    return {
        "work_context": "",
        "personal_context": "",
        "top_of_mind": [],
        "brief_history": "",
        "recent_months": "",
    }


class ProfileBuilder:
    """LLM-backed builder. The chat LLM is constructed lazily and reused
    across requests (mirrors ``MacroIntentClassifier``)."""

    _llm: Any = None
    # Fingerprint of the LLM config the cached instance was built from — see
    # factory.llm_revision. Without it the model stays pinned until restart.
    _llm_revision: str | None = None
    _lock = threading.Lock()

    @classmethod
    def _get_llm(cls) -> Any:
        from ask_llm_gateway.application.factory import llm_revision

        revision = llm_revision()
        if cls._llm is not None and cls._llm_revision == revision:
            return cls._llm
        with cls._lock:
            if cls._llm is not None and cls._llm_revision == revision:
                return cls._llm
            from ask_llm_gateway.application.factory import build_llm

            cfg_path = Path("config/settings.json")
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cls._llm = build_llm(cfg)
            cls._llm_revision = revision
            return cls._llm

    @classmethod
    def reset(cls) -> bool:
        """Drop the cached LLM. Returns True if a build had been cached."""
        with cls._lock:
            had = cls._llm is not None
            cls._llm = None
            cls._llm_revision = None
            return had

    def build(
        self,
        user_id: str,
        display_name: str,
        role: str,
        messages: list[dict[str, Any]],
    ) -> ProfileBuildResponse:
        """Synthesize a profile from the user's chat history.

        Returns an empty profile (with timestamp) when the user has no history
        yet or when the LLM call fails — both are treated the same on the UI
        side ("not enough history" message).
        """
        ts = datetime.now(UTC).isoformat()

        if not messages:
            empty = _empty_profile()
            return ProfileBuildResponse(**empty, last_updated=ts)

        # Cap at 200 latest messages, truncate each to 400 chars.
        conv_lines: list[str] = []
        for msg in messages[-200:]:
            role_label = str(msg.get("role", "")).capitalize()
            content = str(msg.get("content", ""))[:400]
            conv_lines.append(f"{role_label}: {content}")
        conversations = "\n".join(conv_lines)

        prompt = _PROFILE_PROMPT.format(
            role=role or "Unknown",
            display_name=display_name or "Unknown",
            conversations=conversations,
        )

        try:
            response = self._get_llm().invoke(prompt)
            text = _strip_code_fences(content_to_text(response))
            parsed = json.loads(text)
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning("profile build failed for %s: %s", user_id, exc)
            empty = _empty_profile()
            return ProfileBuildResponse(**empty, last_updated=ts)

        # Defensive — backfill any missing key from the empty template.
        empty = _empty_profile()
        for key, default in empty.items():
            parsed.setdefault(key, default)

        return ProfileBuildResponse(
            work_context=str(parsed.get("work_context", "") or ""),
            personal_context=str(parsed.get("personal_context", "") or ""),
            top_of_mind=list(parsed.get("top_of_mind") or []),
            brief_history=str(parsed.get("brief_history", "") or ""),
            recent_months=str(parsed.get("recent_months", "") or ""),
            last_updated=ts,
        )
