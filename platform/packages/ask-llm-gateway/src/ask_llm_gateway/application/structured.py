"""Schema-enforced structured output over any gateway-built chat model.

One call, one contract: ``invoke_structured(llm, schema=..., system=..., user=...)``
returns ``(parsed, tokens, error)`` where ``parsed`` is a validated instance of
``schema`` or ``None``. It NEVER raises — provider capability gaps surface as
``error`` so callers can degrade gracefully (retry, or fall back to a plain
prompt-then-parse path).

Why the shape is what it is (verified against the pinned stacks, 2026-08-12):

* Both classes ``build_llm`` can return implement LangChain's
  ``with_structured_output``: ``ChatLiteLLM`` (langchain-litellm, default method
  ``json_schema``) and ``ChatBedrockConverse`` (langchain-aws, tool-calling).
* ``include_raw=True`` is mandatory here — without it the chain returns only the
  parsed object and the ``usage_metadata`` needed for token accounting is lost.
  The raw ``AIMessage`` rides along as ``out["raw"]``.
* Failure is often SILENT, not raised: this repo sets ``litellm.drop_params=True``,
  so a provider without tool/response_format support just ignores the schema and
  answers prose — the parser then yields ``parsed=None`` with the reason in
  ``parsing_error``. Callers MUST branch on ``parsed is None``, never assume.
* The model-level ``AutoTrackingCallback`` (TokenTracker) keeps firing —
  ``with_structured_output`` wraps the same model instance, so contextvar-based
  accounting is unaffected by this helper.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StructuredResult:
    """Outcome of one structured invocation. ``parsed`` is an instance of the
    requested schema, or ``None`` — then ``error`` says why."""

    parsed: Any | None
    tokens: int
    error: str | None = None


def _tokens_of(message: Any) -> int:
    usage = getattr(message, "usage_metadata", None) or {}
    if isinstance(usage, dict):
        return int(usage.get("total_tokens", 0) or 0)
    return 0


def invoke_structured(llm: Any, *, schema: type, system: str, user: str) -> StructuredResult:
    """Invoke ``llm`` forcing its output into ``schema`` (a Pydantic model class).

    Never raises. Token count comes from the raw message's ``usage_metadata``
    (0 when the provider ships none or the call failed before a response).
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        runnable = llm.with_structured_output(schema, include_raw=True)
    except Exception as exc:  # noqa: BLE001 — capability gap at bind time
        return StructuredResult(parsed=None, tokens=0, error=f"structured bind failed: {exc}")

    try:
        out = runnable.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 — provider/transport error at invoke time
        return StructuredResult(parsed=None, tokens=0, error=f"structured invoke failed: {exc}")

    # include_raw=True contract: {"raw": AIMessage, "parsed": schema|None,
    # "parsing_error": Exception|None} — identical across both model classes.
    if isinstance(out, dict):
        tokens = _tokens_of(out.get("raw"))
        parsed = out.get("parsed")
        if parsed is not None:
            return StructuredResult(parsed=parsed, tokens=tokens)
        err = out.get("parsing_error")
        reason = str(err) if err else "model returned no structured payload (tool call absent)"
        logger.warning("structured output unparsed: %s", reason)
        return StructuredResult(parsed=None, tokens=tokens, error=reason)

    # Defensive: an implementation that ignored include_raw and returned the
    # parsed object directly. Tokens are unrecoverable in that shape.
    if isinstance(out, schema):
        return StructuredResult(parsed=out, tokens=0)
    return StructuredResult(
        parsed=None, tokens=0, error=f"unexpected structured result type: {type(out).__name__}"
    )
