# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask_intent_resolution.flash.infrastructure.rag_service — vectorstore
initialisation for the Flash strategy.

Iter N: absorbed from packages/ask-flash-rag (was Iter 8.9 promotion of
chat/rag_service.py). The embedder is built through the canonical
`ask_llm_gateway.application.factory.build_embedder`, and the
vectorstore client itself lives in `ask_knowledge_graph.infrastructure`
(KG is the semantic owner of every ASK OpenSearch index, including the
RAG collections). Flash is just one of its consumers.
"""

from __future__ import annotations

from typing import Any


def init_vectorstores(settings: dict[str, Any], env: str | None = None):
    """Return `(schema_vs, docs_vs)` built from the project settings.

    ``env`` (``'dev'`` / ``'prod'`` / ``None``) selects which env-suffixed
    OpenSearch indices the vectorstores connect to (UX_CHANGES audit CH-2 +
    Iter 4 read cutover). ``None`` keeps the legacy un-suffixed indices,
    used by batch / CLI callers that never specify an environment.

    The Flash strategy holds the resulting vectorstores in its env-bound
    bundle cache, so this function is invoked at most once per (process, env)
    pair — there is no benefit to memoising the embedder separately.
    """
    from ask_knowledge_graph.infrastructure.rag_vectorstore_client import (
        get_or_create_opensearch_vectorstore,
    )
    from ask_llm_gateway.application.factory import build_embedder

    embeddings = build_embedder(settings)
    os_cfg = settings.get("opensearch", {})
    schema_vs = get_or_create_opensearch_vectorstore(os_cfg, "rag_schema", embeddings, env=env)
    docs_vs = get_or_create_opensearch_vectorstore(
        os_cfg, "rag_data_product_docs", embeddings, env=env
    )
    return schema_vs, docs_vs
