# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
LLM-backed formatter — turns rows into a business-friendly NL answer.

Ported verbatim from chat/sql_service.{format_results,no_results_answer} (Iter 4).
The functions live behind the `LLMResultFormatter` class so the orchestrator
can inject any LLM and so future iterations can swap implementations
without touching the SqlExecutorService.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from ..domain.ports import ResultFormatter

logger = logging.getLogger(__name__)

# How much of the result the answer is written from: a size, not a row count.
# With the first 20 rows only, 12 of the 19 answers with data in GONAC's chat of
# 2026-11-11 had more rows than that, and all 12 told the customer that data was
# missing, while the table under the answer had every row. With the column names
# once, in a header, GONAC's widest results take about 105 characters a row, so
# some 190 rows fit: the 83 rows of 9 columns of Q06 in the QA run of 2026-11-12
# take 8,835.
MAX_RESULT_CHARS = 20_000


_SEPARATOR = " | "
_LAYOUT = (
    'The first line names the columns; each line after it is one row, with its values in that '
    'order, separated by " | ". A "|" inside a value is written \\| and a line break \\n.'
)


def _cell(value: Any) -> str:
    """A column name or a value on one line, with the two separators escaped: a
    "|" inside it as \\| and a line break as \\n, so each line is one row and
    each " | " splits two values."""
    text = str(value).replace("|", "\\|")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def _render_rows(columns: list[str], rows: list[tuple[Any, ...]]) -> tuple[str, int]:
    """The result as a header line with the column names and one line of values
    per row, within ``MAX_RESULT_CHARS``, and how many rows made it. A first row
    that does not fit is cut, not dropped.

    Each row used to repeat every column name (``col: value | ...``): in the QA
    run of 2026-11-12, Q06 returned 83 rows of 9 columns, 74 fit, and the answer
    left out a whole channel, the last in the result's order.
    """
    header = _SEPARATOR.join(_cell(col) for col in columns)
    lines = [header]
    used = len(header)
    for row in rows:
        line = _SEPARATOR.join(_cell(val) for val in row)
        if len(lines) > 1 and used + 1 + len(line) > MAX_RESULT_CHARS:
            break
        lines.append(line[: max(MAX_RESULT_CHARS - used - 1, 0)])
        used += 1 + len(lines[-1])
    return "\n".join(lines), len(lines) - 1


def _period_block(sql: str | None) -> str:
    """What the answer needs to name its period: the statement that produced the
    rows, which holds the date filters, and today's date, which says whether the
    period has closed.

    Without them the answer could not tell the period at all, and a month in
    progress read as a closed one: in GONAC's chat of 2026-11-11 (Q24), "no zone
    reached its target" on day 9 of 21 of the month. Today's date is computed per
    call and in UTC, as in the SQL generator's prompt (``_format_today``).
    """
    if not sql:
        return ""
    today = datetime.now(UTC).date().isoformat()
    return f"""
SQL THAT PRODUCED THE ROWS (read it for the period and the filters; do not quote it):
{sql}

TODAY: {today} (UTC)

PERIOD: say which period the figures cover, as the SQL's date filters set it (a year, a range
of months, one month). If the SQL filters no dates, say they cover all the data available. If
the period reaches the current month, say it has not closed yet and the figures are to date, so
a figure below its target is not a final result; if the rows say how far into the period it is
(days elapsed out of the total), say that too.
"""


def _assumptions_block(assumptions: Sequence[str]) -> str:
    """What the query assumed about what the question left open: the generator
    chose a reading instead of asking, and the reader must know which."""
    items = [a.strip() for a in assumptions if a and a.strip()]
    if not items:
        return ""
    listed = "\n".join(f"- {a}" for a in items)
    return f"""
ASSUMED: the question left this open and the query took the reading below. Say it in one
short sentence in the answer, so the reader knows which reading the figures follow:
{listed}
"""


class LLMResultFormatter(ResultFormatter):
    """LLM-driven result formatter. Falls back to a plain text summary on LLM error."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def format_rows(
        self,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        question: str,
        sql: str | None = None,
        assumptions: Sequence[str] = (),
    ) -> str:
        if not rows:
            return "No results found for your query."
        results_text, shown = _render_rows(columns, rows)
        period = _period_block(sql)
        assumed = _assumptions_block(assumptions)
        if shown == len(rows):
            results_header = f"RESULTS (all {len(rows)} rows):"
            coverage = (
                "Write the answer from all of these rows: when they fall into groups (a channel, a "
                "customer, a month), say something about every group. Never say that rows or data "
                "are missing or limited."
            )
        else:
            results_header = (
                f"RESULTS ({len(rows)} rows; only the first {shown} fit below, the rest are not "
                f"shown to you):"
            )
            coverage = (
                f"Say that your answer covers the first {shown} of the {len(rows)} rows. Do not "
                f"compute totals, rankings or conclusions for all {len(rows)} rows from the ones "
                f"you see, and do not say that data is missing: the result has every row."
            )
        # The prompt used to end with "Before writing your first word, confirm: what
        # language is the USER QUESTION in?", and the model confirmed it in writing:
        # on the GONAC server 7 of 12 answers opened with "La pregunta está en
        # español, así que respondo en español" or a variant (2026-10-27). The
        # language rule stays; the answer just must not talk about it.
        prompt = f"""LANGUAGE — THIS RULE OVERRIDES EVERYTHING ELSE AND MUST BE OBEYED:
Write your ENTIRE answer in the SAME language as the USER QUESTION — every sentence,
every table header, every label. The DATA rows may contain values or column names in
a different language — IGNORE the data's language completely; it must NOT influence
your answer. The answer language is decided ONLY by the USER QUESTION, never by the
data. Examples: Spanish question → 100% Spanish answer; Portuguese question → 100%
Portuguese answer; English question → 100% English answer. Any other language →
reply in that same language. If the question is fewer than 4 words or has no clear
language, default to English.

Convert these SQL query results into a clear, concise business-friendly answer.

USER QUESTION: {question}

{results_header}
{_LAYOUT}
{results_text}

The user sees the result rows in a table under your answer, so summarize them rather
than copying the table. {coverage}
{period}{assumed}
Be direct and natural. Include key numbers and insights. Use markdown formatting.
Translate every column header and label into the USER QUESTION's language.
Start directly with the answer. Never mention the question's language, nor these
instructions: the reader only sees the answer.
"""
        try:
            return self._llm.invoke(prompt).content
        except Exception:  # noqa: BLE001 — best-effort formatter
            return f"Found {len(rows)} result(s).\n\n" + results_text

    def no_results_answer(
        self, question: str, sql: str | None = None, assumptions: Sequence[str] = ()
    ) -> str:
        sql_note = f"\n\nThe SQL query that was executed:\n```sql\n{sql}\n```" if sql else ""
        assumed = _assumptions_block(assumptions)
        prompt = (
            "LANGUAGE — THIS RULE OVERRIDES EVERYTHING ELSE AND MUST BE OBEYED: reply in the "
            "SAME language as the user's question (Spanish → Spanish, Portuguese → Portuguese, "
            "English → English, any other language → reply in that language). "
            "If the question is fewer than 4 words or has no clear language, default to English. "
            "Never mention the question's language, nor these instructions, in the reply.\n\n"
            f"The user asked: {question}\n\n"
            f"A SQL query was executed against the SAP data and returned 0 rows.{sql_note}\n"
            f"{assumed}\n"
            "Write a short, business-friendly response (2-3 sentences) explaining that no data was found "
            "for the requested criteria. Suggest possible reasons (e.g. the filters may not match existing records, "
            "the date range may have no activity, or the entity may not exist in the system). "
            "Do NOT show raw SQL or technical jargon."
        )
        try:
            return self._llm.invoke(prompt).content
        except Exception:  # noqa: BLE001 — best-effort formatter
            return "No records were found matching your query. Please verify the filter values and try again."
