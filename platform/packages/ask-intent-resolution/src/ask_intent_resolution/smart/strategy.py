"""
SmartStrategy — Iter 3 refactor.

Stops at IR resolution: catalog + LLM-as-retriever (entity selection) + Dijkstra
path resolution. Does NOT call the SQL generator. The orchestrator chains
SqlGenerationService afterwards.

Iter 2 wrapped the full v2 graph; Iter 3 invokes the same v2 services directly
to surface IR + edges + YAMLs (raw_yaml fetched from OpenSearch).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from ..application._helpers import _load_settings, _trace
from ..domain.errors import StrategyExecutionError
from ..domain.ports import ResolutionRequest
from ..domain.result import IntentResolutionResult

logger = logging.getLogger(__name__)


class SmartStrategy:
    """Lazy-singleton wrapper around the v2 IR + path-resolution services.

    UX_CHANGES audit (Iter 4 read cutover): bundle cache is keyed by
    publish environment (``dev`` / ``prod`` / ``None`` legacy) so reads
    hit the right env-suffixed OpenSearch indices via
    ``OpenSearchAskRepository(env=...)``.
    """

    # Keyed on (llm_revision, env) — the bundle holds an LLM whose model is
    # baked into the ChatLiteLLM constructor, so without the revision in the key
    # a model switch in ASK Setup would not take effect until restart. See
    # ``ask_llm_gateway.application.factory.llm_revision``.
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
        from ask_llm_gateway.application.factory import llm_revision

        revision = llm_revision()
        key = (revision, env)
        cached = cls._bundles.get(key)
        if cached is not None:
            return cached
        with cls._lock:
            cached = cls._bundles.get(key)
            if cached is not None:
                return cached

            from ask_intent_resolution.smart.application.catalog_service import (
                CatalogService,  # type: ignore[import-not-found]
            )
            from ask_intent_resolution.smart.application.entity_selector import (  # type: ignore[import-not-found]
                EntitySelectorService,
            )
            from ask_intent_resolution.smart.application.path_resolver import (
                PathResolver,  # type: ignore[import-not-found]
            )
            from ask_knowledge_graph.infrastructure.opensearch_reader import (
                OpenSearchKnowledgeGraphReader,
            )
            from ask_knowledge_graph.infrastructure.opensearch_repository import (  # type: ignore[import-not-found]
                OpenSearchAskRepository,
            )
            from ask_llm_gateway.application.factory import build_llm

            cfg = _load_settings()
            llm = build_llm(cfg)
            os_repo = OpenSearchAskRepository(env=env)
            kg_reader = OpenSearchKnowledgeGraphReader(os_repo)
            catalog_service = CatalogService(os_repository=os_repo)
            entity_selector = EntitySelectorService(llm=llm, catalog_service=catalog_service)
            path_resolver = PathResolver(os_repository=os_repo)
            allowed_ids = CatalogService.resolve_active_entity_ids(cfg)
            bundle = {
                "catalog_service": catalog_service,
                "entity_selector": entity_selector,
                "path_resolver": path_resolver,
                "kg_reader": kg_reader,  # Iter 4 — replaces direct os_repo.client.mget
                "os_repo": os_repo,  # legacy v2 services still receive this
                "allowed_ids": allowed_ids,
                "llm": llm,
            }
            # Evict superseded revisions so a process that has seen several model
            # switches keeps at most one bundle per env.
            for stale in [k for k in cls._bundles if k[0] != revision]:
                del cls._bundles[stale]
            cls._bundles[key] = bundle
            return bundle

    def resolve(self, request: ResolutionRequest) -> IntentResolutionResult:
        bundle = self._get_bundle(request.env)
        started = time.monotonic()

        history = "\n".join(
            f"{turn.get('role', '?')}: {turn.get('content', '')}"
            for turn in (request.conversation_history or [])
        )

        # Workspace scope (Iter 1): when the orchestrator resolved the active
        # workspace's entity_ids, use them directly. Falls back to the legacy
        # ``pipeline_v2.active_profile`` allowlist for CLI / batch callers that
        # don't pass a workspace.
        if request.allowed_entity_ids is not None:
            # Scope contract: an empty list is a REAL empty scope (the workspace
            # resolves to no entities answerable in this env → return nothing).
            # Do NOT coerce ``set()`` to None — that would open the whole catalog.
            _resolved_allowed_ids: set[str] | None = set(request.allowed_entity_ids)
        else:
            _resolved_allowed_ids = bundle["allowed_ids"]

        # ── Phase 1: entity selection (LLM-as-retriever) ────────────────────
        # DEBUG catalog visibility
        _catalog = bundle["catalog_service"].get_catalog(allowed_ids=_resolved_allowed_ids)
        _gold = [e.id for e in _catalog.entries if e.layer == "gold"]
        _silver = [e.id for e in _catalog.entries if e.layer == "silver"]
        print(
            f"[smart] catalog={len(_catalog.entries)} entities | gold={_gold} | silver={_silver}",
            flush=True,
        )

        try:
            selector_out = bundle["entity_selector"].select(
                request.question,
                allowed_ids=_resolved_allowed_ids,
                conversation_history=history,
                organization_context=request.organization_context,
            )
        except Exception as exc:  # noqa: BLE001
            raise StrategyExecutionError(f"smart.entity_selector failed: {exc}") from exc

        print(
            f"[smart] selected base_entity={selector_out.ir.base_entity!r} reasoning={selector_out.ir.reasoning!r}",
            flush=True,
        )

        if selector_out.invalid_entity_ids or selector_out.ir is None:
            err = f"entity selector produced invalid entity ids: {selector_out.invalid_entity_ids}"
            return IntentResolutionResult(
                plan={},
                yamls=[],
                edges=[],
                disambiguation=None,
                error=err,
                trace=_trace(started, "smart"),
                sql=None,
                rows=None,
                answer=err,
            )

        ir = selector_out.ir

        # ── Phase 2: deterministic path resolution (Dijkstra over edges) ────
        try:
            resolved = bundle["path_resolver"].resolve(ir, allowed_entities=_resolved_allowed_ids)
        except Exception as exc:  # noqa: BLE001
            raise StrategyExecutionError(f"smart.path_resolver failed: {exc}") from exc

        all_entity_ids = list(resolved.all_entities or [])
        # ── Fetch raw_yaml via KnowledgeGraphReader (Iter 4) ────────────────
        # Replaces the Iter 3 _fetch_yamls helper that poked os_repo.client
        # directly. The reader returns a dict keyed by id; missing entities
        # are silently dropped so the strategy stays fault-tolerant.
        yaml_by_id = bundle["kg_reader"].mget_raw_yaml(all_entity_ids)
        yamls = [yaml_by_id.get(eid, "") for eid in all_entity_ids]

        # Edges as a flat list of dicts for downstream SQL generation
        edges_dict: list[dict[str, Any]] = []
        for path in resolved.paths or []:
            for edge in getattr(path, "edges", None) or []:
                edges_dict.append(_serialize_v2_edge(edge))

        return IntentResolutionResult(
            plan=ir.model_dump() if hasattr(ir, "model_dump") else ir.dict(),
            yamls=[{"id": eid, "raw_yaml": y} for eid, y in zip(all_entity_ids, yamls)],
            edges=edges_dict,
            disambiguation=None,
            error=None,
            trace=_trace(
                started,
                "smart",
                notes=f"entities={len(all_entity_ids)} edges={len(edges_dict)}",
            ),
            sql=None,
            rows=None,
            answer="",
        )


def _serialize_v2_edge(edge: Any) -> dict[str, Any]:
    if isinstance(edge, dict):
        return edge
    out: dict[str, Any] = {}
    for attr in (
        "source_entity",
        "target_entity",
        "source_table",
        "target_table",
        "join_keys",
        # Verbatim authored predicate — authoritative when `join_keys` is empty
        # (multi-key AND, IN (...), ...).
        "join_predicate",
        "join_type",
        "cardinality",
        "traversal_cost",
        "aggregation_safety",
        # Carries the curator's grain/dedup caveat into the prompt.
        "description",
        "cross_module",
        "semantic_label",
        "is_reverse",
    ):
        val = getattr(edge, attr, None)
        if val is None:
            continue
        out[attr] = val.value if hasattr(val, "value") else val
    return out
