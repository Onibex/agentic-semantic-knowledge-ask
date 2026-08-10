"""
src/pipeline_v2/application/path_resolver.py
─────────────────────────────────────────────────────────────────────────────
PathResolver — Determinístico. Resuelve paths de base_entity → cada traversal
target usando el Edge Registry + Dijkstra.

Spec ref:
  Sec. 7.3 Edge Registry fields: source_node, target_node, conditions,
    cardinality, traversal_cost, is_reverse, semantic_label, cross_module.
  Sec. 8.2 Path Selection Rules:
    1. Grain correctness (no aplicada por ahora — placeholder).
    2. Aggregation safety (filter aggregation_safety != "unsafe").
    3. Lowest cost (Dijkstra con weight=traversal_cost).
    4. Shortest path (tie-break implícito en Dijkstra).
  Sec. 8.3 Multi-Hop Cross-Module Query Planning.

Implementación:
  - Scroll sobre ask-edge-registry-v1 al primer uso.
  - Construye NetworkX DiGraph (nodos = entity_ids, aristas = EdgeInfo).
  - shortest_path con weight=traversal_cost entre base_entity y cada target.
  - Opcionalmente filtra por `allowed_entities` (scope del data product activo).
"""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx
from opensearchpy.helpers import scan

from ask_intent_resolution.smart.domain.ir import SemanticPlanIRv2
from ask_intent_resolution.smart.domain.path import EdgeInfo, ResolvedPlan, TraversalPath

logger = logging.getLogger(__name__)


class PathResolver:
    """Dijkstra sobre ask-edge-registry-v1. Sin LLM, sin state-mutating side effects."""

    EDGE_INDEX = "ask-edge-registry-v1"

    def __init__(self, os_repository):
        """
        Args:
            os_repository: OpenSearchAskRepository de v1. Lee edges del registry.
        """
        self._repo = os_repository
        self._edges_cache: list[EdgeInfo] | None = None
        self._graph_cache: nx.DiGraph | None = None

    # ── Public API ──────────────────────────────────────────────────────────

    def resolve(
        self,
        ir: SemanticPlanIRv2,
        *,
        allowed_entities: set[str] | None = None,
    ) -> ResolvedPlan:
        """
        Para cada target en ir.traversals[], calcula path óptimo desde
        ir.base_entity. Devuelve ResolvedPlan consolidado.

        Args:
            ir: Semantic Plan IR v2 (output del EntitySelectorService).
            allowed_entities: si se provee, sólo se usan edges donde AMBAS
                puntas están en el set (filtro por scope del data product).

        Returns:
            ResolvedPlan con paths + unresolved_targets.
        """
        base = ir.base_entity
        if not base:
            return ResolvedPlan(
                base_entity_id="",
                paths=[],
                all_entities=[],
                unresolved_targets=list(ir.traversals or []),
            )

        graph = self._get_graph(allowed_entities=allowed_entities)

        # Si base_entity no está en el grafo, no hay paths posibles
        if base not in graph.nodes:
            return ResolvedPlan(
                base_entity_id=base,
                paths=[],
                all_entities=[base],
                unresolved_targets=list(ir.traversals or []),
            )

        paths: list[TraversalPath] = []
        unresolved: list[str] = []
        all_entities: set[str] = {base}

        for target in ir.traversals or []:
            if target == base:
                continue
            if target not in graph.nodes:
                unresolved.append(target)
                continue
            try:
                node_chain = nx.shortest_path(graph, source=base, target=target, weight="weight")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                unresolved.append(target)
                continue

            edges_in_path = [
                graph.edges[u, v]["edge_info"] for u, v in zip(node_chain, node_chain[1:])
            ]
            total_cost = sum(e.traversal_cost for e in edges_in_path)

            paths.append(
                TraversalPath(
                    base_entity=base,
                    target_entity=target,
                    entity_chain=list(node_chain),
                    edges=edges_in_path,
                    total_cost=total_cost,
                    grain_preserved=True,  # placeholder — enforcement futuro
                    aggregation_safe=all(e.aggregation_safety != "unsafe" for e in edges_in_path),
                )
            )
            all_entities.update(node_chain)

        return ResolvedPlan(
            base_entity_id=base,
            paths=paths,
            all_entities=sorted(all_entities),
            unresolved_targets=unresolved,
        )

    def refresh(self) -> None:
        """Invalida cache de edges + grafo para forzar re-fetch."""
        self._edges_cache = None
        self._graph_cache = None

    # ── Caching layer ────────────────────────────────────────────────────────

    def _get_graph(self, *, allowed_entities: set[str] | None = None) -> nx.DiGraph:
        """
        Devuelve un DiGraph. Si allowed_entities se provee, construye un grafo
        nuevo filtrado (no muta el cache global).
        """
        edges = self._get_edges()
        if allowed_entities is None:
            if self._graph_cache is None:
                self._graph_cache = self._build_graph(edges)
            return self._graph_cache
        # Filtered graph: always fresh (cheap; 72 edges)
        filtered = [
            e
            for e in edges
            if e.source_entity in allowed_entities and e.target_entity in allowed_entities
        ]
        return self._build_graph(filtered)

    def _get_edges(self) -> list[EdgeInfo]:
        """Fetch edges de OpenSearch. Cache en memoria."""
        if self._edges_cache is None:
            self._edges_cache = list(self._load_edges_from_opensearch())
        return self._edges_cache

    # ── internals ────────────────────────────────────────────────────────────

    def _load_edges_from_opensearch(self):
        """Scroll + map cada doc a EdgeInfo."""
        query = {"query": {"match_all": {}}}
        # env-aware: read the repo's resolved edge index (dev/prod), not the literal.
        for hit in scan(self._repo.client, index=self._repo.INDEX_EDGE, query=query):
            src = hit.get("_source") or {}
            edge = self._doc_to_edge(src)
            if edge is not None:
                yield edge

    @staticmethod
    def _doc_to_edge(src: dict[str, Any]) -> EdgeInfo | None:
        """Map _source de OS a EdgeInfo. None si faltan campos críticos."""
        source_entity = src.get("source_node") or ""
        target_entity = src.get("target_node") or ""
        if not source_entity or not target_entity:
            return None

        # conditions -> join_keys. BOTH sides required: a pre-alignment document
        # stores an unparsed multi-key predicate as `left_field` with an empty
        # `right_field`, which is not a join key — it is the whole predicate, and it
        # is recovered as `join_predicate` below instead.
        join_keys: list[tuple[str, str]] = []
        salvaged_predicate = ""
        for cond in src.get("conditions") or []:
            left = cond.get("left_field") or ""
            right = cond.get("right_field") or ""
            if left and right:
                join_keys.append((left, right))
            elif left or right:
                salvaged_predicate = salvaged_predicate or left or right

        # Normalizar join_type (ej. "LEFT OUTER" -> "LEFT", "RIGHT OUTER" -> "RIGHT")
        raw_join = (src.get("join_type") or "LEFT").upper().strip()
        first_token = raw_join.split()[0] if raw_join else "LEFT"
        if first_token not in {"INNER", "LEFT", "RIGHT", "FULL", "CROSS"}:
            first_token = "LEFT"

        # Normalizar cardinality
        card_raw = (src.get("cardinality") or "").lower()
        valid_cards = {
            "one_to_one",
            "one_to_many",
            "many_to_one",
            "many_to_many",
        }
        cardinality = card_raw if card_raw in valid_cards else None

        try:
            traversal_cost = float(src.get("traversal_cost", 1.0) or 1.0)
        except (TypeError, ValueError):
            traversal_cost = 1.0

        # Closed set (`AggregationSafety`). Read from the document instead of the
        # former hardcoded "safe", which made the `unsafe` filter in `_build_graph`
        # unreachable. An out-of-set value is coerced to "safe" WITH A LOG rather
        # than allowed to raise: raising here is swallowed by the `except` below,
        # which silently deletes the edge from the graph.
        safety = (src.get("aggregation_safety") or "safe").strip().lower()
        if safety not in ("safe", "requires_dedup", "unsafe"):
            logger.warning(
                "Edge %s -> %s has unrecognised aggregation_safety %r; treating as 'safe'",
                source_entity,
                target_entity,
                src.get("aggregation_safety"),
            )
            safety = "safe"

        try:
            return EdgeInfo(
                source_entity=source_entity,
                target_entity=target_entity,
                join_keys=join_keys,
                join_type=first_token,
                cardinality=cardinality,
                traversal_cost=traversal_cost,
                aggregation_safety=safety,
                cross_module=bool(src.get("cross_module", False)),
                semantic_label=src.get("semantic_label"),
                is_reverse=bool(src.get("is_reverse", False)),
                source_table=src.get("source_table") or "",
                target_table=src.get("target_table") or "",
                join_predicate=(
                    src.get("join_predicate")
                    or salvaged_predicate
                    or " AND ".join(f"{left} = {right}" for left, right in join_keys)
                ),
                description=src.get("description"),
            )
        except Exception:
            logger.warning(
                "Edge %s -> %s dropped: could not build EdgeInfo from its document",
                source_entity,
                target_entity,
                exc_info=True,
            )
            return None

    @staticmethod
    def _build_graph(edges: list[EdgeInfo]) -> nx.DiGraph:
        """Construye DiGraph con traversal_cost como weight."""
        g = nx.DiGraph()
        for edge in edges:
            if edge.aggregation_safety == "unsafe":
                # Filtro spec Sec. 8.2 regla 2. Live as of the aggregation_safety
                # wiring — it was unreachable while `_doc_to_edge` hardcoded "safe".
                # Logged because dropping an edge silently removes paths from the
                # graph, and "no path found" is indistinguishable from "no edge
                # declared" downstream.
                logger.info(
                    "Edge %s -> %s excluded from the traversal graph: aggregation_safety=unsafe",
                    edge.source_entity,
                    edge.target_entity,
                )
                continue
            # Si ya hay un edge entre esos dos nodos con menor weight, lo mantenemos
            existing = g.get_edge_data(edge.source_entity, edge.target_entity)
            if existing and existing.get("weight", float("inf")) <= edge.traversal_cost:
                continue
            g.add_edge(
                edge.source_entity,
                edge.target_entity,
                weight=edge.traversal_cost,
                edge_info=edge,
            )
        return g
