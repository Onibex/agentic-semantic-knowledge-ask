"""
src/pipeline_v2/domain/path.py
─────────────────────────────────────────────────────────────────────────────
Modelos del grafo de paths — salida del PathResolver.

Spec ref: Sec. 8.1 (Traversal Path Definition), Sec. 7.3 (Edge Registry).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Cardinality = Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
JoinType = Literal["INNER", "LEFT", "RIGHT", "FULL", "CROSS"]
# Must stay identical to `Relationship.aggregation_safety` in
# ask_knowledge_graph.domain.nodes — this is the READ side of the same closed set.
# It used to be `["safe", "unsafe", "conditional"]`: it omitted `requires_dedup`
# (the only non-default value in production use) and invented `conditional`
# (no doc, no YAML, zero uses). That was inert only while `path_resolver` hardcoded
# "safe" on read-back; the moment the field was actually read, every
# `requires_dedup` edge raised here, got swallowed by `_edge_from_source`'s blanket
# `except`, and vanished from the DiGraph with no log.
AggregationSafety = Literal["safe", "requires_dedup", "unsafe"]


class EdgeInfo(BaseModel):
    """Un edge resuelto del ask-edge-registry-v1."""

    source_entity: str
    target_entity: str
    # NOTE: there is no `relationship_type` here on purpose. It used to exist and was
    # populated with the *semantic_label*, not the cardinality — a duplicate of the
    # `semantic_label` field below with no renderer of its own. The cardinality lives
    # in `cardinality`, which is what the edge document actually stores.
    join_keys: list[tuple[str, str]] = Field(
        default_factory=list,
        description="Pares (source_field, target_field)",
    )
    join_type: JoinType = "LEFT"
    cardinality: Cardinality | None = None
    traversal_cost: float = 1.0
    aggregation_safety: AggregationSafety = "safe"
    cross_module: bool = False
    semantic_label: str | None = None
    is_reverse: bool = False

    # Physical table of each side (`db_table_name`), so a consumer never has to infer
    # that `gold_s4h_inventory_situation` and `GOLD_INVENTORY_SITUATION` are the same
    # table — the id and the physical name differ by more than case.
    source_table: str = ""
    target_table: str = ""

    # The authored predicate, verbatim. AUTHORITATIVE whenever `join_keys` is empty,
    # which is every predicate that is not a single simple comparison (multi-key
    # `AND`, `IN (...)`, ...).
    join_predicate: str = ""

    # The curator's business meaning + grain/dedup caveat (SILVER §7.4 / GOLD §6.5).
    description: str | None = None

    def as_sql_hint(self) -> str:
        """Renderiza el edge como línea declarativa para inyectar al prompt."""
        keys_str = ", ".join(f"{s}={t}" for s, t in self.join_keys) or self.join_predicate or "?"
        return (
            f"# Edge: {self.source_entity} {self.join_type} JOIN "
            f"{self.target_entity} ON {keys_str} "
            f"(cost={self.traversal_cost}, cross_module={self.cross_module})"
        )


class TraversalPath(BaseModel):
    """Un path entre base_entity y un target (secuencia ordenada de edges).

    Spec Sec. 8.1: entity_chain + edge_sequence + cardinality_propagation +
    grain_impact + allowed_dimensions + cost_score.
    """

    base_entity: str
    target_entity: str
    entity_chain: list[str] = Field(
        default_factory=list,
        description="IDs ordenados, empezando por base_entity terminando en target",
    )
    edges: list[EdgeInfo] = Field(default_factory=list)
    total_cost: float = 0.0
    grain_preserved: bool = True
    aggregation_safe: bool = True

    def is_single_hop(self) -> bool:
        return len(self.edges) == 1

    def has_cross_module_hop(self) -> bool:
        return any(e.cross_module for e in self.edges)


class ResolvedPlan(BaseModel):
    """Output completo del PathResolver — listo para el SQL generator."""

    base_entity_id: str
    paths: list[TraversalPath] = Field(default_factory=list)
    all_entities: list[str] = Field(
        default_factory=list,
        description="Todas las entities involucradas (base + targets + intermedios)",
    )
    unresolved_targets: list[str] = Field(
        default_factory=list,
        description="Entity IDs que no se pudieron alcanzar desde base_entity",
    )

    def is_complete(self) -> bool:
        """True si todos los traversals del IR fueron resueltos."""
        return len(self.unresolved_targets) == 0
