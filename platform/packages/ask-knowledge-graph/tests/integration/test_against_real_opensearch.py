# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Opt-in integration test for OpenSearchKnowledgeGraphReader against a live
OpenSearch instance.

Skipped unless ASK_RUN_KG_INTEGRATION=1 — same gating pattern as the
benchmark + smoke tests. Use it to validate after a deploy when you want
to confirm the wrapper still maps the production OpenSearch responses
into the Protocol shape correctly.
"""

from __future__ import annotations

import os

import pytest


def _flag_active() -> bool:
    return os.environ.get("ASK_RUN_KG_INTEGRATION", "").strip() == "1"


pytestmark = pytest.mark.skipif(
    not _flag_active(),
    reason="ASK_RUN_KG_INTEGRATION=1 required to hit a live OpenSearch.",
)


@pytest.fixture(scope="module")
def reader():
    """Build the reader against the project's real OpenSearch repo."""
    import sys
    from pathlib import Path

    legacy_path = Path(__file__).resolve().parents[4] / "legacy"
    if str(legacy_path) not in sys.path:
        sys.path.insert(0, str(legacy_path))

    from ask_knowledge_graph.infrastructure.opensearch_reader import (
        OpenSearchKnowledgeGraphReader,
    )
    from ask_knowledge_graph.infrastructure.opensearch_repository import (
        OpenSearchAskRepository,
    )

    return OpenSearchKnowledgeGraphReader(OpenSearchAskRepository())


def test_get_lightweight_entities_returns_list(reader):
    entries = reader.get_lightweight_entities()
    assert isinstance(entries, list)
    if entries:
        assert "id" in entries[0]


def test_get_all_edges_returns_list(reader):
    edges = reader.get_all_edges()
    assert isinstance(edges, list)


def test_mget_raw_yaml_with_known_ids_or_empty(reader):
    """Pulls a small batch by id; tolerant if the registry is empty/different."""
    entries = reader.get_lightweight_entities()
    if not entries:
        pytest.skip("entity registry is empty")
    sample_ids = [e["id"] for e in entries[:3] if e.get("id")]
    out = reader.mget_raw_yaml(sample_ids)
    assert isinstance(out, dict)
    # Each returned id must be one we asked for
    assert set(out.keys()).issubset(set(sample_ids))
