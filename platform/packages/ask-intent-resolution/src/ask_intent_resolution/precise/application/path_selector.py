from typing import Any

import networkx as nx

from ask_knowledge_graph.domain.graph_models import RelationEdge


class PathSelectorService:
    def __init__(self, edge_repository):
        """
        edge_repository: adaptador que extrae todas las relaciones (edges)
                         desde el Edge Registry en OpenSearch.

        Edges + NetworkX graph se cachean a nivel de instancia (lazy load).
        Edge Registry cambia solo cuando se re-ingestan entidades — usa
        `refresh()` para invalidar el cache cuando eso ocurra.
        """
        self.edge_repository = edge_repository
        # Grafo no dirigido (viajes simétricos en ambas direcciones).
        self.graph: nx.Graph = nx.Graph()
        self._cached_edges: list[RelationEdge] | None = None
        self._graph_built: bool = False

    def refresh(self) -> None:
        """Invalida el cache de edges + grafo. Llamar después de re-ingerir
        edges en el Edge Registry para que la próxima query los recoja."""
        self._cached_edges = None
        self._graph_built = False
        self.graph.clear()

    def _get_edges(self) -> list[RelationEdge]:
        """Lazy load + cache de los edges del registry."""
        if self._cached_edges is None:
            self._cached_edges = self.edge_repository.get_all_edges() or []
            print(
                f"🔁 [PathSelector] loaded {len(self._cached_edges)} edges "
                f"from registry (cached for this session)"
            )
        return self._cached_edges

    def _build_graph(self):
        """Construye (una sola vez) el grafo en memoria desde los edges
        cacheados. Llamadas subsecuentes son no-op."""
        if self._graph_built:
            return
        self.graph.clear()
        for edge in self._get_edges():
            self.graph.add_edge(
                edge.source_node,
                edge.target_node,
                weight=edge.traversal_cost,
                edge_data=edge,
            )
        self._graph_built = True

    # ── Plan v1 Step 4: CONTEXT EXPANSION (semi-deterministic hybrid path) ──
    # Takes anchor YAMLs from `EntityResolutionService.select_relevant_yamls`
    # and expands to neighboring entities reachable in ≤ max_hops via the edge
    # registry. The expanded set is what gets fed to the FreeformSQLGenerator
    # as schema context.
    #
    # This is NOT JOIN-path selection (that job belongs to
    # `select_resolved_paths`). It is breadth-first context curation:
    # we want the LLM to SEE related facts/dimensions so it can
    # compose cross-entity queries. Uniform BFS is the right tool here;
    # Dijkstra with weights is used downstream for actual path ranking.
    def expand_context(
        self,
        anchor_yamls: list[dict[str, Any]],
        max_hops: int = 2,
        max_total_yamls: int = 10,
        include_bronze: bool = False,
        allowed_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Expand a set of anchor YAMLs with their graph neighbors.

        Args:
            anchor_yamls:     Output of `select_relevant_yamls()`. Each entry
                              must have at minimum `id` and `raw_yaml` keys.
            max_hops:         BFS radius. 2 hops covers typical fact→dim→ref.
            max_total_yamls:  Cap on the total size of the returned list
                              (anchors + neighbors). Guards against token
                              blow-up when anchors sit in a dense graph region.
            include_bronze:   If True, include Bronze-layer neighbors. Default
                              False to avoid noise from raw SAP tables.
            allowed_ids:      Workspace scope. When provided, BFS neither
                              crosses nor adds neighbors outside this set — so
                              a `relationship`/edge from an in-scope anchor to
                              an out-of-workspace entity (e.g. a Gold belonging
                              to another business domain) cannot leak into the
                              SQL schema context. The anchors themselves are
                              already scoped by `select_relevant_yamls`; this
                              extends the same allowlist to the edge expansion.
                              None = whole registry (no scope).

        Returns:
            list[dict] — same shape as `select_relevant_yamls()` output plus an
            extra `hop_distance` key (0 for anchors, 1..N for neighbors).
            Ordering: anchors preserved in their given order, then neighbors
            sorted by (hop_distance asc, id asc) for determinism.

        Notes:
          - The graph is undirected, so expansion is symmetric.
          - Neighbors without a `raw_yaml` stored in OpenSearch are skipped
            with a warning (same policy as `select_relevant_yamls`).
          - If an anchor id is absent from the graph (e.g. an entity with no
            edges), it is still returned but contributes no neighbors.
        """
        if not anchor_yamls:
            return []

        # Annotate anchors with hop_distance=0, preserving given order + shape
        result: list[dict[str, Any]] = []
        anchor_ids: set = set()
        for a in anchor_yamls:
            aid = a.get("id")
            if not aid or aid in anchor_ids:
                continue
            anchor_ids.add(aid)
            enriched = dict(a)
            enriched.setdefault("hop_distance", 0)
            result.append(enriched)

        if max_hops <= 0 or len(result) >= max_total_yamls:
            return result[:max_total_yamls]

        # (Re)build the edge graph from the Edge Registry.
        self._build_graph()

        # Workspace scope: confine the BFS to the allowlist. A neighbor outside
        # the set is neither added NOR used as a stepping stone, so context
        # expansion can never pull a Gold (or any entity) that belongs to a
        # different business domain into this query.
        # Scope contract: None = no scope; [] = empty scope (an empty set keeps
        # only the anchors). Branch on `is not None`, NOT truthiness.
        scope: set[str] | None = set(allowed_ids) if allowed_ids is not None else None

        # Multi-source BFS. `visited[id] = min_hop_distance_from_any_anchor`
        visited: dict[str, int] = {aid: 0 for aid in anchor_ids}
        frontier: list[str] = [aid for aid in anchor_ids if aid in self.graph]

        for hop in range(1, max_hops + 1):
            next_frontier: list[str] = []
            for node in frontier:
                try:
                    neighbors = list(self.graph.neighbors(node))
                except Exception:
                    continue
                for n in neighbors:
                    if n in visited:
                        continue
                    if scope is not None and n not in scope:
                        continue  # out-of-workspace neighbor — skip + don't traverse
                    visited[n] = hop
                    next_frontier.append(n)
            frontier = next_frontier
            if not frontier:
                break

        # Resolve layer filter. Silver + Gold only — the `metric` layer was
        # removed from the semantic layer; legacy metric documents left in the
        # registry until the purge runs must not re-enter the schema context.
        allowed_layers = {"silver", "gold"}
        if include_bronze:
            allowed_layers.add("bronze")

        # Collect NEW neighbor ids (not already anchors), sorted for determinism
        neighbor_ids = sorted(
            (nid for nid in visited if nid not in anchor_ids),
            key=lambda nid: (visited[nid], nid),
        )

        fetched = 0
        skipped = 0
        for nid in neighbor_ids:
            if len(result) >= max_total_yamls:
                break
            try:
                source = self.edge_repository.get_entity_by_id(nid)
            except Exception as e:
                print(f"⚠️  [Context Expand] fetch failed for '{nid}': {e}")
                skipped += 1
                continue
            if not source:
                skipped += 1
                continue

            layer = (source.get("layer") or "").lower()
            if layer not in allowed_layers:
                skipped += 1
                continue

            raw_yaml = source.get("raw_yaml", "") or ""
            if not raw_yaml.strip():
                print(
                    f"⚠️  [Context Expand] Skipping neighbor '{nid}' — "
                    f"no raw_yaml stored in OpenSearch."
                )
                skipped += 1
                continue

            module = source.get("module", "")
            if isinstance(module, list):
                module = ",".join(m for m in module if m)

            result.append(
                {
                    "id": nid,
                    "name": source.get("name"),
                    "layer": layer,
                    "module": module,
                    "entity_role": (source.get("entity_role") or "").lower(),
                    "raw_yaml": raw_yaml,
                    "final_score": 0.0,  # not from the retriever
                    "hop_distance": visited[nid],
                }
            )
            fetched += 1

        print(
            f"🧭 [Context Expand] anchors={len(anchor_ids)} "
            f"neighbors_added={fetched} skipped={skipped} "
            f"total={len(result)} (cap={max_total_yamls}, hops={max_hops})"
        )
        return result

    # ── CONNECTIVITY REPORT (Plan v1 — 2-pass freeform) ─────────────────────
    # Checks whether a set of entity ids forms a single connected component
    # in the edge graph. Used to WARN the LLM (not block) when multiple Gold
    # anchors are disconnected — the LLM then knows to request a Silver
    # bridge in its `need_more_context` response.
    def connectivity_report(self, entity_ids: list[str]) -> dict[str, Any]:
        """
        Report whether `entity_ids` are all reachable from each other.

        Returns:
            {
              "connected":        bool,        # True if all ids in one component
              "components":       list[list],  # groups of ids per connected component
              "missing_in_graph": list[str],   # ids not present as nodes in the graph
            }
        """
        if not entity_ids or len(entity_ids) < 2:
            return {
                "connected": True,
                "components": [list(entity_ids)] if entity_ids else [],
                "missing_in_graph": [],
            }

        self._build_graph()

        missing: list[str] = [eid for eid in entity_ids if eid not in self.graph]
        present: list[str] = [eid for eid in entity_ids if eid in self.graph]

        if not present:
            return {
                "connected": False,
                "components": [[eid] for eid in entity_ids],
                "missing_in_graph": missing,
            }

        # Union-find via NetworkX: find connected_components of the subgraph
        # induced by `present`, but neighbors can be anywhere in the full graph.
        # We use reachability from each `present` id.
        visited: dict[str, int] = {}
        component_id = 0
        for eid in present:
            if eid in visited:
                continue
            # BFS from eid through the full graph, but only record hits that are
            # in `present` — that's what matters for "are these ids connected".
            stack: list[str] = [eid]
            seen: set = {eid}
            while stack:
                node = stack.pop()
                try:
                    for n in self.graph.neighbors(node):
                        if n not in seen:
                            seen.add(n)
                            stack.append(n)
                except Exception:
                    continue
            for other in present:
                if other in seen and other not in visited:
                    visited[other] = component_id
            component_id += 1

        # Group by component
        groups: dict[int, list[str]] = {}
        for eid, cid in visited.items():
            groups.setdefault(cid, []).append(eid)
        components = [sorted(v) for v in groups.values()]
        # Each disconnected-in-graph id becomes its own component
        for eid in missing:
            components.append([eid])

        return {
            "connected": len(components) == 1 and not missing,
            "components": components,
            "missing_in_graph": missing,
        }

    # ── Plan v1 Step 6: EXPLICIT EDGES HINT (semi-deterministic) ────────────
    # Returns the edges (JOIN conditions) that connect entities in the given
    # scope. Consumed by `FreeformSQLGeneratorService` to inject an authoritative
    # JOIN-paths block into the prompt, so the LLM does not have to re-infer
    # join conditions from the YAML `relationships` sections.
    #
    # Reverse edges (`is_reverse=True`) are filtered out — the forward edge
    # already carries the condition and direction information, and including
    # both would double the prompt size without new information.
    def get_edges_between(
        self,
        entity_ids: list[str],
    ) -> list[RelationEdge]:
        """
        Extract forward edges whose both endpoints belong to `entity_ids`.

        Args:
            entity_ids: list of entity ids returned by `expand_context`.

        Returns:
            list[RelationEdge] with source_node, target_node, conditions,
            join_type, cardinality, traversal_cost. Deduped (same source+target
            pair only appears once, keeping the lowest-cost edge). Ordered by
            (source_node, target_node) for deterministic prompts.
        """
        if not entity_ids or len(entity_ids) < 2:
            return []

        scope = set(entity_ids)
        all_edges: list[RelationEdge] = self._get_edges()

        best_by_pair: dict[tuple, RelationEdge] = {}
        for edge in all_edges:
            if edge.is_reverse:
                continue
            if edge.source_node not in scope or edge.target_node not in scope:
                continue
            key = tuple(sorted((edge.source_node, edge.target_node)))
            prev = best_by_pair.get(key)
            if prev is None or edge.traversal_cost < prev.traversal_cost:
                best_by_pair[key] = edge

        return sorted(
            best_by_pair.values(),
            key=lambda e: (e.source_node, e.target_node),
        )

    # ── Dijkstra path selection for the semi-deterministic flow ─────────────
    # Spec §8.2: path selection rules are grain > aggregation_safety > cost > hops.
    # Works from anchors + expanded scope (no compiler-era `ResolvedPlan`).
    #
    # `select_resolved_paths` picks a `base_entity` (first fact anchor, else
    # highest-scored anchor) and computes Dijkstra shortest paths from it to
    # every other entity in the scope, ranked by total traversal_cost.
    # It reports `unreachable` entities so the LLM can be told up-front which
    # paths do not exist, instead of inventing them.
    #
    # grain_impact is approximated from edge cardinality (no aggregation_safety
    # field exists on RelationEdge today): any one_to_many or many_to_many
    # segment in the path → "fan_out_risk".
    def select_resolved_paths(
        self,
        anchors: list[dict[str, Any]],
        expanded_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Dijkstra-rank paths from the base entity to every other entity in scope.

        Args:
            anchors:      Phase 2 output — ordered by final_score desc.
            expanded_ids: Optional list of entity ids from Phase 3 expansion.
                          If provided, Dijkstra targets are (anchors ∪ expanded).
                          If None, only anchors are used as targets.

        Returns:
            dict with:
              base_entity:  entity id chosen as the Dijkstra source.
              paths:        list[dict] ordered by total_cost asc, each with:
                              target, entity_chain, edges (list of dicts),
                              total_cost, hops, grain_impact ("safe"|"fan_out_risk").
              unreachable:  list[str] — ids in scope with no path from base.
        """
        if not anchors:
            return {"base_entity": None, "paths": [], "unreachable": []}

        # Pick base: prefer fact, then highest score, then first.
        def _anchor_priority(a: dict[str, Any]) -> tuple:
            role = (a.get("entity_role") or "").lower()
            is_fact = 0 if role == "fact" else 1
            # final_score is float; negate so higher wins in ascending sort
            score = -(a.get("final_score") or 0.0)
            return (is_fact, score)

        ranked = sorted(anchors, key=_anchor_priority)
        base_entity = ranked[0].get("id")
        if not base_entity:
            return {"base_entity": None, "paths": [], "unreachable": []}

        # Build target set (scope minus base)
        scope_ids: list[str] = []
        seen: set = set()
        for a in anchors:
            aid = a.get("id")
            if aid and aid not in seen:
                scope_ids.append(aid)
                seen.add(aid)
        for eid in expanded_ids or []:
            if eid and eid not in seen:
                scope_ids.append(eid)
                seen.add(eid)

        targets = [eid for eid in scope_ids if eid != base_entity]
        if not targets:
            return {
                "base_entity": base_entity,
                "paths": [],
                "unreachable": [],
            }

        self._build_graph()

        paths: list[dict[str, Any]] = []
        unreachable: list[str] = []

        if base_entity not in self.graph:
            # Base is isolated — everything is unreachable.
            return {
                "base_entity": base_entity,
                "paths": [],
                "unreachable": targets,
            }

        for target in targets:
            if target not in self.graph:
                unreachable.append(target)
                continue
            try:
                node_path = nx.shortest_path(
                    self.graph, source=base_entity, target=target, weight="weight"
                )
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                unreachable.append(target)
                continue

            edge_list: list[dict[str, Any]] = []
            total_cost = 0.0
            fan_out = False
            for i in range(len(node_path) - 1):
                u, v = node_path[i], node_path[i + 1]
                edge_data: RelationEdge = self.graph[u][v]["edge_data"]
                total_cost += edge_data.traversal_cost
                card = (
                    edge_data.cardinality.value
                    if hasattr(edge_data.cardinality, "value")
                    else str(edge_data.cardinality)
                )
                if card in ("one_to_many", "many_to_many"):
                    fan_out = True
                join_type = (
                    edge_data.join_type.value
                    if hasattr(edge_data.join_type, "value")
                    else str(edge_data.join_type)
                )
                edge_list.append(
                    {
                        "source": u,
                        "target": v,
                        "join_type": join_type,
                        "cardinality": card,
                        "traversal_cost": edge_data.traversal_cost,
                        "conditions": [
                            {
                                "left_field": c.left_field,
                                "right_field": c.right_field,
                                "operator": c.operator,
                            }
                            for c in (edge_data.conditions or [])
                        ],
                    }
                )

            paths.append(
                {
                    "target": target,
                    "entity_chain": node_path,
                    "edges": edge_list,
                    "total_cost": total_cost,
                    "hops": len(node_path) - 1,
                    "grain_impact": "fan_out_risk" if fan_out else "safe",
                }
            )

        paths.sort(key=lambda p: (p["total_cost"], p["hops"], p["target"]))

        return {
            "base_entity": base_entity,
            "paths": paths,
            "unreachable": sorted(unreachable),
        }
