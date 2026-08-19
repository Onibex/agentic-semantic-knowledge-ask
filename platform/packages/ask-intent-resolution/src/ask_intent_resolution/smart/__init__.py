# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Smart strategy — catalog-driven Graph RAG, aligned to the ASK specification.

  Layer 1 — Intent Resolution   ← hybrid BM25+kNN+RRF with module_filter +
                                  layer_priority=gold_first
  Layer 2 — Semantic Plan IR    ← LLM produces IR with base_entity +
                                  traversals[] + filters + time_context
  Layer 3 — Path Resolution     ← deterministic Dijkstra over the Edge
                                  Registry honouring traversal_cost,
                                  cross_module and grain correctness

Flow:

    User question
        │
        ▼
    CatalogService.get_catalog()                     ← cached, Silver+Gold
        │
        ▼
    EntitySelectorService.select(question, catalog)  ← LLM call (SemanticPlanIRv2)
        │
        ▼
    PathResolver.resolve(ir)                         ← deterministic
                Uses: ask-edge-registry-v1
                Output: list[TraversalPath] with edges + join_keys

The strategy STOPS at path resolution. SQL generation and execution are
chained downstream by the orchestrator (ask-sql-generation → ask-sql-executor).

Principles:

1. Bronze is never queried — only Silver + Gold enter the catalog.
2. The `metric` layer is removed: out of the catalog and out of retrieval.
3. The cross_module flag on edges is first-class for planning.
4. Fail loud on missing critical fields — no silent defaults.
"""
