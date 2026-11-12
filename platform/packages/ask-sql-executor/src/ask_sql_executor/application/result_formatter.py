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
from typing import Any

from ..domain.ports import ResultFormatter

logger = logging.getLogger(__name__)

# How much of the result the answer is written from: a size, not a row count.
# With the first 20 rows only, 12 of the 19 answers with data in GONAC's chat of
# 2026-11-11 had more rows than that, and all 12 told the customer that data was
# missing, while the table under the answer had every row. At about 185
# characters a row (GONAC's widest results), some 100 rows fit, as many as the
# chat's table shows; that QA's longest reference result, 77 rows, takes 14,300.
MAX_RESULT_CHARS = 20_000


def _render_rows(columns: list[str], rows: list[tuple[Any, ...]]) -> tuple[str, int]:
    """The rows as ``col: value | ...`` lines within ``MAX_RESULT_CHARS``, and
    how many made it. A first row wider than the limit is cut, not dropped."""
    lines: list[str] = []
    used = 0
    for row in rows:
        line = " | ".join(f"{col}: {val}" for col, val in zip(columns, row))
        if lines and used + len(line) > MAX_RESULT_CHARS:
            break
        lines.append(line[:MAX_RESULT_CHARS])
        used += len(line) + 1
    return "\n".join(lines), len(lines)


class LLMResultFormatter(ResultFormatter):
    """LLM-driven result formatter. Falls back to a plain text summary on LLM error."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def format_rows(
        self,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        question: str,
    ) -> str:
        if not rows:
            return "No results found for your query."
        results_text, shown = _render_rows(columns, rows)
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
{results_text}

The user sees the result rows in a table under your answer, so summarize them rather
than copying the table. {coverage}

Be direct and natural. Include key numbers and insights. Use markdown formatting.
Translate every column header and label into the USER QUESTION's language.
Start directly with the answer. Never mention the question's language, nor these
instructions: the reader only sees the answer.
"""
        try:
            return self._llm.invoke(prompt).content
        except Exception:  # noqa: BLE001 — best-effort formatter
            return f"Found {len(rows)} result(s).\n\n" + results_text

    def no_results_answer(self, question: str, sql: str | None = None) -> str:
        sql_note = f"\n\nThe SQL query that was executed:\n```sql\n{sql}\n```" if sql else ""
        prompt = (
            "LANGUAGE — THIS RULE OVERRIDES EVERYTHING ELSE AND MUST BE OBEYED: reply in the "
            "SAME language as the user's question (Spanish → Spanish, Portuguese → Portuguese, "
            "English → English, any other language → reply in that language). "
            "If the question is fewer than 4 words or has no clear language, default to English. "
            "Never mention the question's language, nor these instructions, in the reply.\n\n"
            f"The user asked: {question}\n\n"
            f"A SQL query was executed against the SAP data and returned 0 rows.{sql_note}\n\n"
            "Write a short, business-friendly response (2-3 sentences) explaining that no data was found "
            "for the requested criteria. Suggest possible reasons (e.g. the filters may not match existing records, "
            "the date range may have no activity, or the entity may not exist in the system). "
            "Do NOT show raw SQL or technical jargon."
        )
        try:
            return self._llm.invoke(prompt).content
        except Exception:  # noqa: BLE001 — best-effort formatter
            return "No records were found matching your query. Please verify the filter values and try again."
