"""Unit tests for Precise context expansion workspace scoping.

Regression: in production, Gold entities that did NOT belong to the active
workspace appeared in chat answers. Root cause — PathSelectorService.expand_context
ran a BFS over the FULL edge registry, so a ``relationship``/edge from an in-scope
anchor to an out-of-workspace entity pulled that entity into the SQL schema
context. Retrieval was already scoped (allowed_ids); the edge expansion was not.

These tests pin the fix: when ``allowed_ids`` is provided, expand_context must
neither add NOR traverse through out-of-scope neighbors. With ``allowed_ids=None``
the old whole-registry behavior is preserved.
"""

from __future__ import annotations

from types import SimpleNamespace

from ask_intent_resolution.precise.application.path_selector import PathSelectorService


def _edge(source: str, target: str, cost: float = 1.0) -> SimpleNamespace:
    # expand_context / _build_graph only read source_node, target_node,
    # traversal_cost — a light stand-in keeps the test free of enum coupling.
    return SimpleNamespace(source_node=source, target_node=target, traversal_cost=cost)


def _entity(eid: str, layer: str = "silver") -> dict:
    return {
        "id": eid,
        "name": eid,
        "layer": layer,
        "module": "sd",
        "entity_role": "dimension",
        "raw_yaml": f"id: {eid}\nlayer: {layer}\n",
    }


class _FakeEdgeRepo:
    """Edge registry stand-in: a fixed edge list + entity lookup."""

    def __init__(self, edges, entities):
        self._edges = edges
        self._entities = entities

    def get_all_edges(self):
        return self._edges

    def get_entity_by_id(self, eid):
        return self._entities.get(eid)


# anchor ── in_scope_dim ── out_of_scope_gold (chain): the gold is reachable in
# 2 hops, but ONLY by stepping through an in-scope dimension.
ANCHOR = "silver_s4h_sd_sales_order"
IN_SCOPE_DIM = "silver_s4h_sd_customer_master"
OUT_GOLD = "gold_s4h_inventory_situation"

EDGES = [_edge(ANCHOR, IN_SCOPE_DIM), _edge(IN_SCOPE_DIM, OUT_GOLD)]
ENTITIES = {
    ANCHOR: _entity(ANCHOR),
    IN_SCOPE_DIM: _entity(IN_SCOPE_DIM),
    OUT_GOLD: _entity(OUT_GOLD, layer="gold"),
}


def _service() -> PathSelectorService:
    return PathSelectorService(_FakeEdgeRepo(EDGES, ENTITIES))


def test_scope_excludes_out_of_workspace_gold():
    svc = _service()
    out = svc.expand_context(
        [{"id": ANCHOR, "raw_yaml": "x"}],
        max_hops=2,
        allowed_ids=[ANCHOR, IN_SCOPE_DIM],  # gold deliberately absent
    )
    ids = {e["id"] for e in out}
    assert ANCHOR in ids
    assert IN_SCOPE_DIM in ids  # in-scope neighbor still expands
    assert OUT_GOLD not in ids  # the leak: must NOT appear


def test_scope_does_not_use_out_of_scope_node_as_stepping_stone():
    """Even if a deeper in-scope entity is only reachable THROUGH an
    out-of-scope node, the out-of-scope node is not traversed."""
    deep = "silver_s4h_sd_deep_entity"
    edges = [_edge(ANCHOR, OUT_GOLD), _edge(OUT_GOLD, deep)]
    entities = {
        ANCHOR: _entity(ANCHOR),
        OUT_GOLD: _entity(OUT_GOLD, layer="gold"),
        deep: _entity(deep),
    }
    svc = PathSelectorService(_FakeEdgeRepo(edges, entities))
    out = svc.expand_context(
        [{"id": ANCHOR, "raw_yaml": "x"}],
        max_hops=3,
        allowed_ids=[ANCHOR, deep],  # deep is allowed but only reachable via gold
    )
    ids = {e["id"] for e in out}
    assert OUT_GOLD not in ids
    assert deep not in ids  # blocked: the only path crosses an out-of-scope node


def test_no_scope_preserves_whole_registry_expansion():
    """allowed_ids=None keeps the original behavior — every reachable neighbor
    (Silver + Gold) is pulled in."""
    svc = _service()
    out = svc.expand_context([{"id": ANCHOR, "raw_yaml": "x"}], max_hops=2, allowed_ids=None)
    ids = {e["id"] for e in out}
    assert {ANCHOR, IN_SCOPE_DIM, OUT_GOLD} <= ids


def test_empty_scope_keeps_only_anchors_not_whole_registry():
    """Contract: allowed_ids=[] is an EMPTY scope, NOT unscoped. The BFS must
    add no neighbors (anchors are already in the result). Treating [] as falsy
    would expand the whole registry — the opposite of the gate."""
    svc = _service()
    out = svc.expand_context([{"id": ANCHOR, "raw_yaml": "x"}], max_hops=2, allowed_ids=[])
    ids = {e["id"] for e in out}
    assert ids == {ANCHOR}  # only the anchor; no neighbor pulled in
