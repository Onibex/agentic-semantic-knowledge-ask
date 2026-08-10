"""
PreciseStrategy — Iter 3 refactor.

Iter 2 wrapped the full v1 ask_graph (IR through SQL execution). Iter 3
splits the SQL phase out: this strategy now invokes Phase 1 (IR + L1/L2/L3
disambiguation) via the legacy fase1_ir_graph sub-graph and runs Phases
2-3 (entity resolution, BFS expansion, Dijkstra path selection) directly
against the legacy services. It STOPS before SQL generation. The
orchestrator chains SqlGenerationService afterwards.

The disambiguation behavior is preserved bit-for-bit because we still use
the legacy fase1 sub-graph instead of re-implementing it.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from ..application._helpers import _load_settings, _trace
from ..domain.errors import StrategyExecutionError
from ..domain.ports import ResolutionRequest
from ..domain.result import (
    Disambiguation,
    IntentResolutionResult,
)

logger = logging.getLogger(__name__)


class PreciseStrategy:
    """Lazy-singleton wrapper around the v1 IR + Phases 2-3 services.

    UX_CHANGES audit (Iter 4 read cutover): bundle cache is keyed by
    publish environment (``dev`` / ``prod`` / ``None`` legacy) so reads
    hit the right env-suffixed OpenSearch indices via
    ``OpenSearchAskRepository(env=...)``. Each env has its own
    fase1_graph + resolver + path_selector built lazily.
    """

    # Keyed on (llm_revision + embedder_revision, env). This bundle wires BOTH
    # an LLM and an embedder into long-lived services (entity resolver, semantic
    # dictionary, fase1 graph), and each bakes its model in at construction — so
    # both fingerprints belong in the key or a provider switch in ASK Setup would
    # not take effect until restart. See ``factory.llm_revision``.
    _bundles: dict[tuple[str, str | None], dict[str, Any]] = {}
    _lock = threading.Lock()

    @classmethod
    def reset(cls) -> bool:
        """Drop every cached env-bound bundle."""
        with cls._lock:
            had = bool(cls._bundles)
            cls._bundles = {}
            return had

    @classmethod
    def _get_bundle(cls, env: str | None) -> dict[str, Any]:
        from ask_llm_gateway.application.factory import embedder_revision, llm_revision

        revision = f"{llm_revision()}//{embedder_revision()}"
        key = (revision, env)
        cached = cls._bundles.get(key)
        if cached is not None:
            return cached
        with cls._lock:
            cached = cls._bundles.get(key)
            if cached is not None:
                return cached

            from ask_intent_resolution.precise.application.entity_resolution import (  # type: ignore[import-not-found]
                EntityResolutionService,
            )
            from ask_intent_resolution.precise.application.ir_generator import (
                IRGeneratorService,  # type: ignore[import-not-found]
            )
            from ask_intent_resolution.precise.application.path_selector import (
                PathSelectorService,  # type: ignore[import-not-found]
            )
            from ask_intent_resolution.precise.graph.fase1_ir_graph import (
                build_fase1_graph,  # type: ignore[import-not-found]
            )
            from ask_knowledge_graph.application._legacy_dictionary import (  # type: ignore[import-not-found]
                SemanticDictionaryService,
            )
            from ask_knowledge_graph.infrastructure.opensearch_repository import (  # type: ignore[import-not-found]
                OpenSearchAskRepository,
            )
            from ask_llm_gateway.application.factory import build_embedder, build_llm

            cfg = _load_settings()
            llm = build_llm(cfg)
            embedder = build_embedder(cfg)
            os_repo = OpenSearchAskRepository(env=env)
            semantic_dict = SemanticDictionaryService(os_client=os_repo.client, embedder=embedder)
            entity_resolver = EntityResolutionService(
                embedder=embedder,
                os_repository=os_repo,
                llm=llm,
                semantic_dictionary=semantic_dict,
            )
            path_selector = PathSelectorService(edge_repository=os_repo)
            ir_generator = IRGeneratorService(llm=llm)

            fase1_graph = build_fase1_graph(
                ir_generator=ir_generator,
                semantic_dictionary=semantic_dict,
                embedder=embedder,
                checkpointer=MemorySaver(),
            )

            hp_cfg = cfg.get("hybrid_pipeline", {}) or {}
            bundle = {
                "fase1_graph": fase1_graph,
                "entity_resolver": entity_resolver,
                "path_selector": path_selector,
                "anchor_top_k": int(hp_cfg.get("anchor_top_k", 3)),
                "expand_max_hops": int(hp_cfg.get("expand_max_hops", 1)),
                "expand_max_total": int(hp_cfg.get("expand_max_total", 5)),
                "llm": llm,
            }
            # Evict superseded revisions so a process that has seen several model
            # switches keeps at most one bundle per env.
            for stale in [k for k in cls._bundles if k[0] != revision]:
                del cls._bundles[stale]
            cls._bundles[key] = bundle
            return bundle

    def resolve(self, request: ResolutionRequest) -> IntentResolutionResult:
        from ask_intent_resolution.precise.domain.ir_models import (
            SemanticPlanIR,  # type: ignore[import-not-found]
        )

        bundle = self._get_bundle(request.env)
        started = time.monotonic()

        thread_id = f"ask-{request.session_id or uuid.uuid4().hex}"

        # ── Phase 1: IR + dictionary disambiguation (legacy sub-graph) ──────
        try:
            phase1_state = bundle["fase1_graph"].invoke(
                {
                    "question": request.question,
                    "original_question": request.question,
                    "user_role_id": "assistant",
                    "user_department": None,
                },
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception as exc:  # noqa: BLE001
            raise StrategyExecutionError(f"precise.fase1.invoke failed: {exc}") from exc

        disambig_msg = phase1_state.get("disambiguation_message")
        if disambig_msg:
            return IntentResolutionResult(
                plan=phase1_state.get("plan_ir_dict") or {},
                yamls=[],
                edges=[],
                disambiguation=Disambiguation(level="L2", message=disambig_msg),
                error=None,
                trace=_trace(started, "precise"),
                sql=None,
                rows=None,
                answer=disambig_msg,
            )

        plan_dict = phase1_state.get("plan_ir_dict")
        err = phase1_state.get("error")
        if err or not plan_dict:
            return IntentResolutionResult(
                plan=plan_dict or {},
                yamls=[],
                edges=[],
                disambiguation=None,
                error=err or "phase1 produced no plan_ir_dict",
                trace=_trace(started, "precise"),
                sql=None,
                rows=None,
                answer=phase1_state.get("response") or f"Phase 1 error: {err}",
            )

        plan_ir = SemanticPlanIR(**plan_dict)

        # ── Phase 2: anchor YAML selection ──────────────────────────────────
        # Workspace scope: restrict the anchor search universe to the workspace's
        # entity ids (None = whole registry). This is THE search-universe
        # reduction for Precise — anchors root the downstream expansion/SQL.
        try:
            anchors = bundle["entity_resolver"].select_relevant_yamls(
                plan_ir,
                top_k=bundle["anchor_top_k"],
                allowed_ids=request.allowed_entity_ids,
            )
        except Exception as exc:  # noqa: BLE001
            raise StrategyExecutionError(f"precise.select_relevant_yamls failed: {exc}") from exc

        # ── Phase 3: BFS context expansion + edges + Dijkstra paths ─────────
        try:
            expanded = bundle["path_selector"].expand_context(
                anchors,
                max_hops=bundle["expand_max_hops"],
                max_total_yamls=bundle["expand_max_total"],
                allowed_ids=request.allowed_entity_ids,
            )
        except Exception as exc:  # noqa: BLE001
            raise StrategyExecutionError(f"precise.expand_context failed: {exc}") from exc

        entity_ids = [e["id"] for e in expanded if e.get("id")]
        edges_raw: list = []
        try:
            edges_raw = bundle["path_selector"].get_edges_between(entity_ids) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("precise.get_edges_between failed: %s", exc)

        edges_dict = [_serialize_edge(e) for e in edges_raw]

        return IntentResolutionResult(
            plan=plan_dict,
            yamls=expanded,
            edges=edges_dict,
            disambiguation=None,
            error=None,
            trace=_trace(
                started, "precise", notes=f"anchors={len(anchors)} expanded={len(expanded)}"
            ),
            # Iter 3: SQL phase moves to ask-sql-generation. These transitional
            # fields are populated only for back-compat with Iter 2 callers
            # until T9 narrows the result and the orchestrator chains directly.
            sql=None,
            rows=None,
            answer="",
        )


def _serialize_edge(e: Any) -> dict[str, Any]:
    """Best-effort dict serialization of legacy RelationEdge / EdgeInfo objects."""
    if isinstance(e, dict):
        return e
    out: dict[str, Any] = {}
    for attr in (
        "source_node",
        "target_node",
        "source_entity",
        "target_entity",
        "source_table",
        "target_table",
        "join_type",
        "join_keys",
        # Verbatim authored predicate — authoritative when `conditions` is empty
        # (multi-key AND, IN (...), ...). Without it the SQL prompt has no join
        # condition at all for those edges.
        "join_predicate",
        "cardinality",
        "traversal_cost",
        "aggregation_safety",
        # Carries the curator's grain/dedup caveat into the prompt.
        "description",
        "cross_module",
        "semantic_label",
        "is_reverse",
    ):
        val = getattr(e, attr, None)
        if val is None:
            continue
        out[attr] = val.value if hasattr(val, "value") else val
    return out


# Iter 2 retained this for backward compat — kept as a no-op symbol so any
# imports that referenced `_normalize_legacy_state` keep resolving until the
# next cleanup. Iter 3 strategies do not use it.
def _normalize_legacy_state(*_args: Any, **_kwargs: Any) -> None:  # pragma: no cover
    raise NotImplementedError(
        "_normalize_legacy_state was removed in Iter 3 — strategies stop at IR now"
    )
