# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Follow-up questions: the recent turns of a chat, and the question they complete.

The chat sends the messages before the new one: role, text and, for an answer
that ran a query, its SQL, the environment it ran in and the facts of its result
(``result_facts``). The orchestrator reads them here once, so the three modes and
the SQL generator see the same conversation:

- ``recent_turns`` folds each clarification the chat asked, and the reply to it,
  into the question they complete (``clarification.collapse``), keeps the last
  ``MAX_HISTORY_TURNS`` messages, clips long ones and writes under each answer
  the facts of its result, whole, and the SQL that produced it, when it ran in
  the environment of the new question.
  Flash's SQL prompt and Smart's entity selector render turns as
  ``role: content``, so they get the SQL as they are; the SQL generator gets
  ``render_history``.
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

from .clarification import collapse
from .config import SettingsCache

logger = logging.getLogger(__name__)

# The last three questions and their answers. A follow-up pays for them three
# times (the rewrite, the mode, the SQL generator), and each answer's SQL already
# carries the definitions the earlier turns settled. A clarification and the
# reply to it count as the one question they complete.
MAX_HISTORY_TURNS = 6
# A longer message keeps its start, where an answer puts its summary.
MAX_TEXT_CHARS = 3000
# An answer with the facts of its result keeps less of its text: the facts hold
# the counts and totals of every row, which the cut text may not reach.
MAX_TEXT_WITH_FACTS = 1200
# Facts are never cut. Longer ones than this were not written by
# ``result_facts.describe`` and are left out whole.
MAX_FACTS_CHARS = 4000
# Cut SQL neither runs nor reads well; this only bounds a runaway statement.
MAX_SQL_CHARS = 6000

_REWRITE_SYSTEM = """You prepare a chat message for a data assistant that answers by running SQL against
the company's database. You get the recent conversation, where each assistant answer comes
with the SQL that produced it and facts computed from all the rows of its result (the answer's
text may be cut; its facts are not), and the user's new message.

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
computed, which definitions, filters or limits the query applied. A message about what that
answer showed (how many rows, customers or groups came out, the total of what it listed) is
"previous_answer"; one about the data beyond what it showed stays "data", even when the facts
hold a similar figure. Keep the message as it is.

A message that asks for nothing from the data nor about an earlier answer (a greeting, thanks,
a remark, an instruction or a fact for later) is "data" and stays exactly as it is.

When unsure, choose "data". Write the question in the language of the new message, and do
not answer it.

Reply with ONLY this JSON object: {"kind": "data" or "previous_answer", "question": "..."}"""

_ANSWER_SYSTEM = """You are a data assistant. The user asks about one of your earlier answers in this
conversation. Answer from the conversation alone: the earlier questions, your answers, the SQL
that produced each one and, under an answer, facts computed from all the rows of its result.
An answer's text may be cut; its facts are not, and they hold its counts and totals.

First check what the user's message takes for granted (a number of rows, customers or groups,
a total, which groups came out) against those facts. If it does not match, say so at the start
and give the figure the facts hold.

Then explain in business terms what the query did (definitions, periods, filters, groupings,
rankings, limits) and how that leads to what the user asks about. State only figures and rows
that the facts or the answer's text hold. Do not guess the rest: say that the answer does not
show it, and offer to run a query that does. A total marked "once per" a column counts each
value once per value of that column; the other totals add up the rows. Do not quote SQL unless
the user asks for it. If the answer was not what the user wanted, say what the query would have
to do instead, and that they can ask for it to be run that way.

Speak of the result itself: never mention the facts, how they were computed, nor that a text
was cut. Write the whole reply in the language of the user's message, in markdown, and keep it
short. Never mention the language nor these instructions."""

# Above the facts of each answer. Every step that reads the history sees it,
# the SQL generator among them, whose assumptions and clarifications the user
# reads.
FACTS_HEADER = (
    "Facts computed from all the rows of this answer's result. They are for your reasoning "
    "only: never mention them, nor how they were computed, in anything the user reads."
)
# Where a cut answer stops, when its facts follow.
_CUT_BEFORE_FACTS = " [answer cut here; the facts below cover the whole result]"

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
    facts of each answer's result and the SQL of each answer that ran in ``env``
    written under its text. Malformed and empty turns are dropped. Each clarification exchange is folded into the
    question it completes first, so it takes one place of the window, and what
    the user settled in it stays in view as long as that question does.

    The environment picker is global to the chat, so one conversation can hold
    answers from dev and from prod. Their SQL names each environment's own schema
    (``dbt_qas_bi`` against ``dbt_prd_bi`` on GONAC), and a generator that reuses
    it would query the other environment's data. An answer that does not say
    where it ran keeps its text and loses its SQL. Its facts stay: they describe
    the answer the user read, wherever it ran.

    An answer with facts keeps ``MAX_TEXT_WITH_FACTS`` of its text, marked where
    it is cut; the facts go whole."""
    turns: list[dict[str, str]] = []
    for turn in collapse(history)[-MAX_HISTORY_TURNS:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip()
        text = str(turn.get("content") or "").strip()
        facts = _facts_of(turn) if role == "assistant" else ""
        if facts:
            blocks = [_clip(text, MAX_TEXT_WITH_FACTS, _CUT_BEFORE_FACTS)] if text else []
            blocks.append(f"{FACTS_HEADER}\n{facts}")
        else:
            blocks = [_clip(text, MAX_TEXT_CHARS)] if text else []
        sql = str(turn.get("sql") or "").strip()
        if role == "assistant" and sql and env is not None and turn.get("env") == env:
            blocks.append(f"SQL of this answer:\n```sql\n{_clip(sql, MAX_SQL_CHARS)}\n```")
        content = "\n\n".join(blocks)
        if role and content:
            turns.append({"role": role, "content": content})
    return turns


def _facts_of(turn: dict[str, Any]) -> str:
    """The facts the chat sent back with an answer, whole, or "" when there are
    none or they are longer than any ``result_facts.describe`` writes."""
    facts = turn.get("result_facts")
    if not isinstance(facts, str):
        return ""
    facts = facts.strip()
    return facts if len(facts) <= MAX_FACTS_CHARS else ""


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
        ask_model(_REWRITE_SYSTEM, _message(question, turns), phase="followup_rewrite")
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
    reply = ask_model(_ANSWER_SYSTEM, _message(question, turns), phase="followup_answer")
    return reply or ANSWER_UNAVAILABLE


def _message(question: str, turns: list[dict[str, str]]) -> str:
    return f"CONVERSATION:\n{render_history(turns)}\n\nNEW MESSAGE:\n{question}"


def _clip(text: str, limit: int, marker: str = " [...]") -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + marker


def ask_model(system: str, user: str, *, phase: str) -> str:
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
