# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Token usage tracking for all LLM calls.

Design:
  - One TokenTracker per user query, published via set_active_tracker().
  - AutoTrackingCallback is attached to every LLM instance by the factory.
  - Services wrap LLM calls in `with track_phase("phase_name"):` to tag records.

Supported response shapes:
  ChatBedrockConverse, SAP ChatOpenAI proxy, native AIMessage.usage_metadata.
"""

from __future__ import annotations

import contextvars
import json
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from ..domain.models import TokenUsageRecord

# ── Context variables ─────────────────────────────────────────────────────────

_active_tracker: contextvars.ContextVar[TokenTracker | None] = contextvars.ContextVar(
    "_ask_llm_gateway_tracker", default=None
)
_active_phase: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_ask_llm_gateway_phase", default="unspecified"
)


def set_active_tracker(tracker: TokenTracker | None) -> None:
    _active_tracker.set(tracker)


def get_active_tracker() -> TokenTracker | None:
    return _active_tracker.get()


def clear_active_tracker() -> None:
    _active_tracker.set(None)


class track_phase:
    """
    Context manager that tags every LLM call inside the block with a phase name.
    Supports nesting — inner phase overrides, outer is restored on exit.

    Usage:
        with track_phase("ir_generation"):
            result = llm.invoke(prompt)
    """

    def __init__(self, phase: str) -> None:
        self._phase = phase
        self._token: contextvars.Token | None = None

    def __enter__(self) -> track_phase:
        self._token = _active_phase.set(self._phase)
        return self

    def __exit__(self, *_) -> None:
        if self._token is not None:
            _active_phase.reset(self._token)


# ── Usage extraction ──────────────────────────────────────────────────────────


def _extract_usage(
    llm_output: dict[str, Any] | None,
    generations: list[list[Any]] | None,
) -> dict[str, int]:
    """
    Normalize token usage from any supported LLM response shape.

    Priority:
      1. llm_output["usage"]       — Bedrock Converse (inputTokens / outputTokens)
      2. llm_output["token_usage"] — SAP ChatOpenAI proxy (prompt_tokens / completion_tokens)
      3. generation.message.usage_metadata — native AIMessage metadata
    """
    if isinstance(llm_output, dict):
        if isinstance(llm_output.get("usage"), dict):
            u = llm_output["usage"]
            return {
                "input_tokens": int(u.get("input_tokens") or u.get("inputTokens") or 0),
                "output_tokens": int(u.get("output_tokens") or u.get("outputTokens") or 0),
            }
        if isinstance(llm_output.get("token_usage"), dict):
            u = llm_output["token_usage"]
            return {
                "input_tokens": int(u.get("prompt_tokens") or 0),
                "output_tokens": int(u.get("completion_tokens") or 0),
            }

    for gen_list in generations or []:
        for gen in gen_list or []:
            msg = getattr(gen, "message", None)
            # 1. LangChain normalized usage_metadata (standard path)
            um = getattr(msg, "usage_metadata", None) if msg is not None else None
            if isinstance(um, dict):
                return {
                    "input_tokens": int(um.get("input_tokens") or 0),
                    "output_tokens": int(um.get("output_tokens") or 0),
                }
            # 2. Bedrock Converse via SAP AI Core: usage lives in response_metadata
            rm = (getattr(msg, "response_metadata", None) or {}) if msg is not None else {}
            if isinstance(rm.get("usage"), dict):
                u = rm["usage"]
                return {
                    "input_tokens": int(u.get("input_tokens") or u.get("inputTokens") or 0),
                    "output_tokens": int(u.get("output_tokens") or u.get("outputTokens") or 0),
                }
            # 3. generation_info fallback
            gi = getattr(gen, "generation_info", None) or {}
            if isinstance(gi, dict) and isinstance(gi.get("usage"), dict):
                u = gi["usage"]
                return {
                    "input_tokens": int(u.get("input_tokens") or u.get("inputTokens") or 0),
                    "output_tokens": int(u.get("output_tokens") or u.get("outputTokens") or 0),
                }

    return {"input_tokens": 0, "output_tokens": 0}


# ── TokenTracker ──────────────────────────────────────────────────────────────


class TokenTracker:
    """
    Accumulates per-call token usage records for a single query.
    Thread-safe. Optionally persists each record as a JSONL line.

    Tokens only — cost is intentionally not tracked. The same model is priced
    differently per channel (Bedrock / Azure / SAP AI Core / direct), so a
    local estimate would misrepresent the real bill; the authoritative cost
    lives in each provider's billing console. Token counts are objective and
    channel-independent.
    """

    def __init__(
        self,
        log_path: Path | None = None,
        query_id: str | None = None,
    ) -> None:
        self.log_path = Path(log_path) if log_path else None
        self.query_id = query_id
        self._records: list[TokenUsageRecord] = []
        self._lock = threading.Lock()

    def record(
        self,
        *,
        phase: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> TokenUsageRecord:
        rec = TokenUsageRecord(
            phase=phase,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            timestamp_utc=datetime.now(UTC).isoformat(),
            query_id=self.query_id,
        )
        with self._lock:
            self._records.append(rec)
            if self.log_path is not None:
                self._append_jsonl(rec)
        return rec

    def _append_jsonl(self, rec: TokenUsageRecord) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        except Exception as exc:
            print(f"[TokenTracker] JSONL write failed: {exc}")

    def records(self) -> list[TokenUsageRecord]:
        with self._lock:
            return list(self._records)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            recs = list(self._records)

        by_phase: dict[str, dict[str, Any]] = {}
        total_in = total_out = 0
        for r in recs:
            total_in += r.input_tokens
            total_out += r.output_tokens
            b = by_phase.setdefault(
                r.phase,
                {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            )
            b["calls"] += 1
            b["input_tokens"] += r.input_tokens
            b["output_tokens"] += r.output_tokens
            b["total_tokens"] += r.total_tokens

        return {
            "query_id": self.query_id,
            "total_calls": len(recs),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "by_phase": by_phase,
            "records": [asdict(r) for r in recs],
        }

    def reset(self) -> None:
        with self._lock:
            self._records.clear()


# ── Callback handler ──────────────────────────────────────────────────────────


class AutoTrackingCallback(BaseCallbackHandler):
    """
    Attached to every LLM instance by the factory.
    Reads the active tracker + phase from contextvars and records each call.
    No-op when no tracker is active.
    """

    def __init__(self, model: str) -> None:
        self.model = model

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001
        tracker = get_active_tracker()
        if tracker is None:
            return
        try:
            usage = _extract_usage(
                getattr(response, "llm_output", None),
                getattr(response, "generations", None),
            )
            tracker.record(
                phase=_active_phase.get(),
                model=self.model,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
            )
        except Exception as exc:
            print(f"[AutoTrackingCallback] on_llm_end failed: {exc}")
