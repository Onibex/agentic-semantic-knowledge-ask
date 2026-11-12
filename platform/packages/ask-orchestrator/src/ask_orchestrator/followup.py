# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Follow-up questions: the recent turns of a chat, and the question they complete.

The chat sends the messages before the new one: role, text and, for an answer
that ran a query, its SQL and the environment it ran in. The orchestrator reads
them here once, so the three modes and the SQL generator see the same
conversation:

- ``recent_turns`` keeps the last ``MAX_HISTORY_TURNS`` messages, clips long
  ones and writes under each answer the SQL that produced it, when it ran in
  the environment of the new question. Flash's SQL prompt and Smart's entity
  selector render turns as ``role: content``, so they get the SQL as they are;
  the SQL generator gets ``render_history``.
- ``resolve_followup`` asks the model, once, whether the new message needs the
  database or asks about an earlier answer, and in the first case rewrites it
  as a question that stands on its own. Precise reads only the question, so the
  rewrite is how a follow-up reaches it.
- ``answer_about_previous`` answers the second case from the turns alone. The
  answer it is asked about already ran; a new query would answer something else.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .config import SettingsCache

logger = logging.getLogger(__name__)

# The last three questions and their answers. A follow-up pays for them three
# times (the rewrite, the mode, the SQL generator), and each answer's SQL already
# carries the definitions the earlier turns settled.
MAX_HISTORY_TURNS = 6
# A longer message keeps its start, where an answer puts its summary.
MAX_TEXT_CHARS = 3000
# Cut SQL neither runs nor reads well; this only bounds a runaway statement.
MAX_SQL_CHARS = 6000

_REWRITE_SYSTEM = """You prepare a chat message for a data assistant that answers by running SQL against
the company's database. You get the recent conversation, where each assistant answer comes
with the SQL that produced it, and the user's new message.

Decide which of two kinds the new message is.

"data": answering it needs the database. A new question, or a change to an earlier query:
run it again, other filters, periods, groupings, rankings, limits or columns. Rewrite it as
ONE question that stands on its own, so that someone who never saw the conversation would
run the same query: carry over from the earlier turns what the message relies on, and what
it leaves open that the conversation already settled (definitions, measures, filters,
periods, groupings, rankings, limits); apply the changes it asks for and keep the rest.
Describe an earlier query in words, never as SQL. A message that already stands on its own
and leaves nothing open stays as it is.

"previous_answer": it asks about an earlier answer itself, and the conversation already
holds what answers it: why the result has those rows or that many, how a figure was
computed, which definitions, filters or limits the query applied. Keep the message as it
is.

When unsure, choose "data". Write the question in the language of the new message, and do
not answer it.

Reply with ONLY this JSON object: {"kind": "data" or "previous_answer", "question": "..."}"""

_ANSWER_SYSTEM = """You are a data assistant. The user asks about one of your earlier answers in this
conversation. Answer from the conversation alone: the earlier questions, your answers and the
SQL that produced each one. Explain in business terms what the query did (definitions,
periods, filters, groupings, rankings, limits) and how that leads to what the user asks
about. Do not quote SQL unless the user asks for it, and do not state figures the
conversation does not hold. If the answer was not what the user wanted, say what the query
would have to do instead, and that they can ask for it to be run that way.

Write the whole reply in the language of the user's message, in markdown, and keep it short.
Never mention the language nor these instructions."""

# The reply when the model fails to answer about an earlier answer. Running the
# message as a new question instead would answer something the user did not ask.
ANSWER_UNAVAILABLE = (
    "I could not answer your question about the previous answer this time. Please ask it again."
)


@dataclass(frozen=True)
class FollowUp:
    """What the pipeline answers: ``question``, standing on its own, or, when
    ``about_previous``, the user's message about an earlier answer."""

    question: str
    about_previous: bool = False


def recent_turns(history: list[dict[str, Any]] | None, env: str | None) -> list[dict[str, str]]:
    """The last ``MAX_HISTORY_TURNS`` messages as ``{role, content}``, with the
    SQL of each answer that ran in ``env`` written under its text. Malformed and
    empty turns are dropped.

    The environment picker is global to the chat, so one conversation can hold
    answers from dev and from prod. Their SQL names each environment's own schema
    (``dbt_qas_bi`` against ``dbt_prd_bi`` on GONAC), and a generator that reuses
    it would query the other environment's data. An answer that does not say
    where it ran keeps its text and loses its SQL."""
    turns: list[dict[str, str]] = []
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip()
        content = _clip(str(turn.get("content") or "").strip(), MAX_TEXT_CHARS)
        sql = str(turn.get("sql") or "").strip()
        if role == "assistant" and sql and env is not None and turn.get("env") == env:
            block = f"SQL of this answer:\n```sql\n{_clip(sql, MAX_SQL_CHARS)}\n```"
            content = f"{content}\n\n{block}" if content else block
        if role and content:
            turns.append({"role": role, "content": content})
    return turns


def render_history(turns: list[dict[str, str]]) -> str:
    """The turns as one text, ``role: content`` per message, oldest first."""
    return "\n\n".join(f"{t.get('role', '?')}: {t.get('content', '')}" for t in turns)


def resolve_followup(question: str, turns: list[dict[str, str]]) -> FollowUp:
    """Whether ``question`` asks about an earlier answer and, if not, the
    question rewritten to stand on its own. Without turns, or when the model
    fails or replies out of shape, the question goes on as it came."""
    if not turns:
        return FollowUp(question)
    parsed = _parse_object(
        _ask(_REWRITE_SYSTEM, _message(question, turns), phase="followup_rewrite")
    )
    if parsed is None:
        return FollowUp(question)
    if parsed.get("kind") == "previous_answer":
        return FollowUp(question, about_previous=True)
    rewritten = str(parsed.get("question") or "").strip()
    return FollowUp(rewritten or question)


def answer_about_previous(question: str, turns: list[dict[str, str]]) -> str:
    """The reply to a message about an earlier answer, from the turns alone, or
    ``ANSWER_UNAVAILABLE`` when the model fails."""
    reply = _ask(_ANSWER_SYSTEM, _message(question, turns), phase="followup_answer")
    return reply or ANSWER_UNAVAILABLE


def _message(question: str, turns: list[dict[str, str]]) -> str:
    return f"CONVERSATION:\n{render_history(turns)}\n\nNEW MESSAGE:\n{question}"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + " [...]"


def _ask(system: str, user: str, *, phase: str) -> str:
    """One model call, tagged ``phase`` in the token breakdown; "" on failure."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from ask_llm_gateway.application.factory import build_llm
    from ask_llm_gateway.infrastructure.response_utils import content_to_text
    from ask_llm_gateway.infrastructure.token_tracker import track_phase

    try:
        llm = build_llm(SettingsCache.get())
        with track_phase(phase):
            response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return content_to_text(response).strip()
    except Exception as exc:  # the message goes on without this step
        logger.warning("follow-up step %s failed: %s", phase, exc)
        return ""


def _parse_object(text: str) -> dict[str, Any] | None:
    """The JSON object in ``text``, fenced or surrounded by prose; else None."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
