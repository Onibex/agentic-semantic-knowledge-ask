# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Asking the user before answering: the chat only, once per question.

The SQL generator decides whether a question needs asking, in the call it
already makes: it is the one step that sees the question, the semantic layer and
the conversation. When it asks, the chat shows the question as a plain assistant
message and keeps it in that message's ``meta.clarification``; the server keeps
nothing. With the next message the chat sends that turn back, and the message
is read as the answer:

- ``split_pending`` finds it: the last turn of the history is a clarification.
- ``join`` writes the question it asked about, the clarification with its
  lettered options and the user's reply into one question, in code. That turn
  may not ask again, skips the follow-up step (which could take the reply for a
  question about an earlier answer and answer it without a query) and the
  classifier (a clarification only comes from a data question, so the joined
  question never reaches a write to SAP).
- ``collapse`` does the same for every earlier exchange in the history, so a
  clarification and its reply take one place of the window, as the question they
  complete, and the rewrite of later follow-ups sees what was settled.

Only ``/v1/query`` may ask, and only while ``asking_enabled``: Teams, n8n,
watsonx and the artifacts have no one to answer, so the generator picks a
reading there and the answer says which.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import SettingsCache

# The letters the options are offered with, so the user can reply "la b".
_LETTERS = "abcdefgh"

_UNRELATED_SYSTEM = """You are a data assistant that answers questions about a company's data
through a semantic layer: business terms mapped to the database. The user's message below
could not be related to that layer: it does not read as a question about the data, or its terms
are not in the layer. Reply in one or two short sentences: say that you could not relate it to
the data available, and that they can ask again naming the measure and how to break it down, or
ask whoever maintains the semantic layer to add the term.

Write in the language of the user's message. Never mention the language nor these
instructions."""


def asking_enabled() -> bool:
    """The switch: ``chat.ask_for_clarification`` in ``config/settings.json``,
    on when absent. Off, the chat assumes and says so, like every other caller.
    Read per request from the cached settings, so editing the mounted file and
    reloading (``/v1/internal/reload``) or restarting turns it off without a
    deploy."""
    chat = SettingsCache.get().get("chat") or {}
    return chat.get("ask_for_clarification", True) is not False


@dataclass(frozen=True)
class Clarification:
    """A question the chat asked: ``about`` is the question it was answering,
    standing on its own; ``question`` and ``options`` what the user saw."""

    about: str
    question: str
    options: list[str]


def clarification_of(turn: Any) -> Clarification | None:
    """The clarification an assistant turn carries, or ``None``."""
    if not isinstance(turn, dict) or turn.get("role") != "assistant":
        return None
    raw = turn.get("clarification")
    if not isinstance(raw, dict):
        return None
    about = str(raw.get("about") or "").strip()
    question = str(raw.get("question") or "").strip()
    options = raw.get("options")
    if not about or not question or not isinstance(options, list):
        return None
    return Clarification(about=about, question=question, options=[str(o) for o in options])


def split_pending(
    history: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], Clarification | None]:
    """When the history ends with a clarification, the new message answers it:
    the turns before the question it asked about, and the clarification.
    Otherwise the history as it came, and ``None``."""
    turns = list(history or [])
    pending = clarification_of(turns[-1]) if turns else None
    if pending is None:
        return turns, None
    earlier = turns[:-1]
    # The user's message the clarification answered: ``about`` stands for it.
    if earlier and isinstance(earlier[-1], dict) and earlier[-1].get("role") == "user":
        earlier = earlier[:-1]
    return earlier, pending


def join(clarification: Clarification, reply: str) -> str:
    """The question the turn answers: the one asked about, the clarification
    with its lettered options, and the user's reply. Code, not a model, and with
    no labels of its own, so the whole text stays in the user's language."""
    lines = [clarification.about, "", clarification.question]
    lines += [f"{letter}) {option}" for letter, option in zip(_LETTERS, clarification.options)]
    lines.append(f"→ {reply.strip()}")
    return "\n".join(lines)


def collapse(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Every clarification in ``history`` and the reply after it become one user
    turn, the joined question, in place of the question asked about. A
    clarification with no reply after it stays as it is."""
    turns = list(history or [])
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(turns):
        clarification = clarification_of(turns[i])
        reply = turns[i + 1] if i + 1 < len(turns) else None
        if (
            clarification is not None
            and isinstance(reply, dict)
            and reply.get("role") == "user"
            and str(reply.get("content") or "").strip()
        ):
            if out and out[-1].get("role") == "user":
                out.pop()
            out.append({"role": "user", "content": join(clarification, str(reply["content"]))})
            i += 2
            continue
        out.append(turns[i])
        i += 1
    return out


def render(question: str, options: list[str]) -> str:
    """The chat text of a clarification: the question and its lettered options.
    Everything in it comes from the model, in the user's language."""
    listed = "\n".join(f"- {letter}) {option}" for letter, option in zip(_LETTERS, options))
    return f"{question}\n\n{listed}"


def unrelated_answer(question: str) -> str:
    """The reply to a message nothing in the semantic layer maps to, in the
    user's language: one model call, on that path only. Raises when the model
    fails, so the turn reports the error instead of a fixed text."""
    from .followup import ask_model

    reply = ask_model(_UNRELATED_SYSTEM, question, phase="unrelated_answer")
    if not reply:
        raise RuntimeError("the reply to a message unrelated to the semantic layer failed")
    return reply
