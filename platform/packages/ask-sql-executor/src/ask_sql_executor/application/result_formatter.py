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
        results_text = "\n".join(
            " | ".join(f"{col}: {val}" for col, val in zip(columns, row)) for row in rows[:20]
        )
        truncated_note = (
            " — only the first 20 are shown below, so do NOT compute totals/aggregates "
            "beyond what the data supports"
            if len(rows) > 20
            else ""
        )
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

RESULTS ({len(rows)} rows{truncated_note}):
{results_text}

Be direct and natural. Include key numbers and insights. Use markdown formatting.
Translate every column header and label into the USER QUESTION's language.
Before writing your first word, confirm: what language is the USER QUESTION in?
Write 100% of your answer in that language.
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
            "If the question is fewer than 4 words or has no clear language, default to English.\n\n"
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
