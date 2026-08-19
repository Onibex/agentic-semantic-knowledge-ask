# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
RAG flow for DOCS_QUERY.

  question
     │  embed
     ▼
  vector ────► docs_retriever.search_data_products  → DocsHits (chunks)
                              │
                              ▼
                  build_prompt(question, hits)
                              │
                              ▼
                       llm.invoke → answer
                              │
                              ▼
                   DocsResponse(answer, citations)

The flow has no other dependencies — the retriever, the embedder and the
LLM are all injected through their Protocols, so the orchestrator wires
the heavy concretes once at startup.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.models import Citation, DocsHit, DocsQuery, DocsResponse
from ..domain.ports import DocsRetriever, DocsService, Embedder

logger = logging.getLogger(__name__)


SNIPPET_MAX_CHARS = 240
DOC_PROMPT_HEADER = (
    "You are a SAP functional consultant. Answer using ONLY the documentation "
    "provided below. Explain clearly from a business perspective. If the "
    "documentation does not contain the answer, say so explicitly — do not "
    "invent fields, tables, or business rules. Cite each source file you "
    "reference."
)


class DocsRagService(DocsService):
    """The default DocsService implementation."""

    def __init__(
        self,
        retriever: DocsRetriever,
        embedder: Embedder,
        llm: Any,
    ) -> None:
        self._retriever = retriever
        self._embedder = embedder
        self._llm = llm

    def answer(self, query: DocsQuery) -> DocsResponse:
        if not query.question or not query.question.strip():
            return DocsResponse(answer="", error="Empty docs question.")

        try:
            vector = self._embedder.embed_query(query.question.strip())
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning("docs.embed_query failed: %s", exc)
            return DocsResponse(
                answer=f"Pipeline error: {exc}",
                error=str(exc),
            )

        try:
            hits = self._retriever.search_data_products(
                text=query.question.strip(),
                vector=vector,
                top_k=query.top_k,
            )
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning("docs.search_data_products failed: %s", exc)
            return DocsResponse(
                answer=f"Pipeline error: {exc}",
                error=str(exc),
            )

        if not hits:
            return DocsResponse(
                answer=(
                    "No documentation matches this question. Try rephrasing "
                    "or ask the Agentic Trainer to ingest the relevant data "
                    "product documentation through the Embeddings admin page."
                ),
                citations=[],
            )

        prompt = _build_prompt(query.question.strip(), hits)
        try:
            answer_text = self._llm.invoke(prompt).content
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning("docs.llm.invoke failed: %s", exc)
            return DocsResponse(
                answer=f"Pipeline error: {exc}",
                citations=_to_citations(hits),
                error=str(exc),
            )

        return DocsResponse(
            answer=answer_text or "",
            citations=_to_citations(hits),
        )


def _build_prompt(question: str, hits: list[DocsHit]) -> str:
    """Assemble the LLM prompt for one DOCS_QUERY call.

    Each hit becomes a `**Source:**` block carrying the chunk text. The
    LLM is instructed to cite the source files by name in the response.
    """
    blocks = []
    for h in hits:
        header = f"**Source:** {h.source_file or '(unknown file)'}"
        if h.data_product_name:
            header += f" — data product: {h.data_product_name}"
        blocks.append(f"{header}\n\n{h.chunk_text.strip()}")
    docs_section = "\n\n---\n\n".join(blocks)
    return (
        f"{DOC_PROMPT_HEADER}\n\n"
        f"USER QUESTION:\n{question}\n\n"
        f"DOCUMENTATION:\n{docs_section}\n\n"
        f"Answer (markdown, concise, cite source files inline):"
    )


def _to_citations(hits: list[DocsHit]) -> list[Citation]:
    return [
        Citation(
            entity_id=h.source_file or h.data_product_name or "doc",
            snippet=_snippet(h.chunk_text),
            score=h.score,
        )
        for h in hits
    ]


def _snippet(text: str) -> str:
    """First N chars of the chunk, single-line, used by the UI as a preview."""
    flat = " ".join((text or "").split())
    return flat[:SNIPPET_MAX_CHARS]
