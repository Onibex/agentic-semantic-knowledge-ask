# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Contract test: the Gold entity document written to the Entity Registry.

`save_gold_node` produces the only document the retrieval layer can score a Gold
on, and it had drifted from `GoldNode` in two ways that together made the Gold
plane unreachable:

1. It read `node.composed_of`, a key `GoldNode` does not carry — so every Gold
   publish raised `AttributeError` and no Gold could be indexed at all.
2. It omitted the three OpenSearch-only fields the Silver branch writes. A Gold
   that did index would be invisible to the `business_terms` clause of BOTH the
   hybrid search and the Gold-rescue query (the mitigation built specifically
   against Gold starvation), would carry no `key_fields_summary` for the
   anti-Lost-in-the-Middle block, and would read back as
   `anti_hallucination_priority: normal` — Silver's tier, inside the re-ranking
   whose only purpose is to rank Gold above Silver.

Both are asserted here against a real `GoldNode`, so the model and its indexer
cannot drift apart again silently.
"""

from __future__ import annotations

from typing import Any

from ask_knowledge_graph.domain.nodes import GoldNode
from ask_knowledge_graph.infrastructure import opensearch_repository as repo_mod
from ask_knowledge_graph.infrastructure.opensearch_repository import OpenSearchAskRepository

_GOLD_YAML: dict[str, Any] = {
    "id": "gold_s4h_mm_inventory_position",
    "internal_id": "GOLD_MM_INVENTORY_POSITION",
    "db_table_name": "GOLD_MM_INVENTORY_POSITION",
    "layer": "gold",
    "version": "1.0",
    "source_system": "s4h",
    "source_system_no": 1,
    "business_process": "SOURCE TO PAY",
    "module": ["mm", "sd"],
    "tag1": "INV",
    "tag2": "MM",
    "name": "inventory_position",
    "description": "Stock position per material and plant.",
    "grain": {
        "entity_grain": ["material", "plant"],
        "business_grain": "one row per material and plant",
    },
    "fields": [
        {
            "name": "material",
            "source": "MATNR",
            "field_role": "identifier",
            "type": "STRING(40)",
            "description": "Material number.",
        },
        {
            "name": "plant",
            "source": "WERKS",
            "field_role": "identifier",
            "type": "STRING(4)",
            "description": "Plant that holds the stock.",
        },
        {
            "name": "unrestricted_stock",
            "source": "LABST",
            "field_role": "measure",
            "type": "DECIMAL(13,3)",
            "description": "Stock available without restriction.",
            "aggregation_behavior": "SUM",
            "synonyms": ["available stock"],
        },
    ],
}


class _FakeEmbedder:
    """Records what text got embedded — the vector itself is irrelevant here."""

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.embedded.append(text)
        return [0.1, 0.2, 0.3]


def _index_gold(embedder: Any | None = None) -> tuple[dict, list[dict]]:
    """Run `save_gold_node` against a captured bulk, return (entity doc, actions)."""
    repo = OpenSearchAskRepository.__new__(OpenSearchAskRepository)
    repo.INDEX_ENTITY = "ask-entity-registry-v1-test"
    repo.INDEX_FIELD = "ask-field-registry-v1-test"
    repo.INDEX_EDGE = "ask-edge-registry-v1-test"
    repo.client = object()
    repo._ensure_indices_exist = lambda: None  # type: ignore[method-assign]

    captured: list[list[dict]] = []

    class _Helpers:
        @staticmethod
        def bulk(_client: Any, actions: list[dict]) -> None:
            captured.append(list(actions))

    original = repo_mod.helpers
    repo_mod.helpers = _Helpers  # type: ignore[assignment]
    try:
        repo.save_gold_node(GoldNode.model_validate(_GOLD_YAML), "layer: gold\n", embedder)
    finally:
        repo_mod.helpers = original

    actions = captured[0]
    entity = next(a["_source"] for a in actions if a["_index"] == "ask-entity-registry-v1-test")
    return entity, actions


def test_gold_indexes_without_composed_of() -> None:
    """The key left the Gold contract; the indexer must not reach for it."""
    entity, _ = _index_gold()
    assert "composed_of" not in entity
    # The physical table is the one thing `composed_of` could ever have restated.
    assert entity["db_table_name"] == "GOLD_MM_INVENTORY_POSITION"


def test_gold_carries_the_retrieval_fields_silver_gets() -> None:
    """Without these three, a published Gold is unfindable or under-ranked."""
    entity, _ = _index_gold()

    # Medallion re-ranking reads this with a "normal" default — absent means Silver's tier.
    assert entity["anti_hallucination_priority"] == "critical"

    # Matched by the hybrid search (`business_terms^1.5`) and by the Gold rescue.
    assert "Stock position per material and plant." in entity["business_terms"]
    assert "Stock available without restriction." in entity["business_terms"]
    assert "available stock" in entity["business_terms"], "field synonyms must reach the index"

    # Anti-Lost-in-the-Middle block: a Gold names its OWN table, having no lineage.
    summary = entity["key_fields_summary"]
    assert "PHYSICAL TABLE: GOLD_MM_INVENTORY_POSITION" in summary
    assert "SAP TABLES" not in summary
    assert "- material:" in summary and "- plant:" in summary
    assert "- unrestricted_stock: SUM of LABST" in summary


def test_gold_embeds_the_same_projection_as_silver() -> None:
    """The embedder is handed `business_terms`, not just name + description."""
    embedder = _FakeEmbedder()
    entity, _ = _index_gold(embedder)

    assert embedder.embedded == [entity["business_terms"]]
    assert entity["embedding"] == [0.1, 0.2, 0.3]


def test_gold_embedding_is_none_without_an_embedder() -> None:
    entity, _ = _index_gold(None)
    assert entity["embedding"] is None


def test_gold_fields_reach_the_field_registry() -> None:
    _, actions = _index_gold()
    fields = [a["_source"] for a in actions if a["_index"] == "ask-field-registry-v1-test"]
    assert {f["name"] for f in fields} == {"material", "plant", "unrestricted_stock"}
    measure = next(f for f in fields if f["name"] == "unrestricted_stock")
    assert measure["field_role"] == "measure"
    assert measure["aggregation_behavior"] == "SUM"
    assert measure["synonyms"] == ["available stock"]
