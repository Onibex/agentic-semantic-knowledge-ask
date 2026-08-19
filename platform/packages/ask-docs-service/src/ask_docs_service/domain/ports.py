# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Ports for the Docs Service.

Critical isolation rule (Iter 5 Q6):
  ask_docs_service does NOT depend on ask_knowledge_graph. The two packages
  are PEERS that happen to query the same OpenSearch backend. The DocsRetriever
  Protocol exists so we can evolve the docs-side retrieval (different weights,
  filters, top-K defaults) without coupling to / regressing the strategies'
  retrieval inside ask_knowledge_graph.

  Concrete impl is `infrastructure.opensearch_docs_retriever.OpenSearchDocsRetriever`,
  which targets the `rag-data-product-docs` index — the collection populated
  by the Embeddings admin page when the user picks "Data Product Documentation".
"""

from __future__ import annotations

from typing import Protocol

from .models import DocsHit, DocsQuery, DocsResponse


class DocsService(Protocol):
    """Inbound — orchestrator-facing."""

    def answer(self, query: DocsQuery) -> DocsResponse: ...


class DocsRetriever(Protocol):
    """Outbound — search backed by OpenSearch but DEDICATED to docs Q&A."""

    def search_data_products(
        self,
        *,
        text: str,
        vector: list[float],
        top_k: int,
    ) -> list[DocsHit]: ...


class Embedder(Protocol):
    """Outbound — embeds the question into a vector for retrieval."""

    def embed_query(self, text: str) -> list[float]: ...
