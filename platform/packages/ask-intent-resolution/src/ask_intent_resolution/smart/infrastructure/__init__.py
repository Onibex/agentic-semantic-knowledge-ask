# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Infrastructure layer — pipeline v2.

Estado actual: VACÍO. Reusamos la infra compartida:
  - OpenSearchAskRepository (ask_knowledge_graph.infrastructure)
  - build_embedder          (ask_llm_gateway.application.factory)
  - build_llm               (ask_llm_gateway.application.factory)

Si v2 necesita infra específica (p.ej. un repo con query patterns distintos),
se agrega aquí sin tocar v1.
"""
