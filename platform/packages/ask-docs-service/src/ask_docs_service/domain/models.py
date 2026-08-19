# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Domain models for Docs queries (data-product Q&A)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DocsQuery:
    """Inputs for one docs question."""

    question: str
    top_k: int = 6


@dataclass(frozen=True)
class DocsHit:
    """One retrieved documentation chunk from the `rag-data-product-docs` index.

    The docs collection stores arbitrary uploaded business documentation
    (PDF / DOCX / TXT) that the user ingests through the Embeddings admin
    page. Each entry is a chunk of the original document, not a YAML
    entity definition — so the model carries `source_file` + `chunk_text`
    rather than `entity_id` + `raw_yaml`.
    """

    source_file: str
    data_product_name: str
    chunk_text: str
    score: float


@dataclass(frozen=True)
class Citation:
    """A single citation surfaced in DocsResponse.

    `entity_id` is an opaque identifier kept for the orchestrator's public
    response shape; for docs hits it is populated with the source file name.
    """

    entity_id: str
    snippet: str
    score: float


@dataclass(frozen=True)
class DocsResponse:
    """Outcome of a docs question. Citations point back to the source files
    that informed the answer so the UI can deep-link to them.
    """

    answer: str
    citations: list[Citation] = field(default_factory=list)
    error: str | None = None
