# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
FlashStrategy — Chunk RAG path. **Bypasses ask-sql-generation by design (Iter 3 Q1).**

Flash is conceptually a single LLM call from question to SQL — it does not
have an explicit IR phase. Routing it through the new SqlGenerationService
would force a synthetic IR step (a second LLM call) and either change the
behavior we promised to preserve, or burn cost on inputs SqlGenerationService
does not actually need.

Iter 3 contract for Flash
─────────────────────────
- The strategy populates `IntentResolutionResult.sql / .rows / .answer`
  directly. It leaves `plan / yamls / edges` empty.
- The orchestrator detects `result.sql is not None` and SKIPS the
  ResolveIntent → SqlGeneration → executor chain for Flash. Flash output
  is final and goes straight to QueryResponse.

Iter N — backend absorbed
─────────────────────────
The chunk-RAG backend that used to live in `ask-flash-rag` (a separate
package) was moved to `ask_intent_resolution.flash.infrastructure.*` so the
mode is symmetric with `precise/` and `smart/` (each mode self-contained
within ask-intent-resolution). Execution + result formatting now go through
`ask-sql-executor.SqlExecutorService.execute_and_format()` — eliminating the
~120 LOC of duplicated `execute_sql` / `format_results` that lived in the
flash sql_service module.
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


class FlashStrategy:
    """Lazy-singleton wrapper around the Chunk RAG (Flash) pipeline.

    UX_CHANGES audit (Iter 4 read cutover): bundle cache is keyed by
    publish environment (``dev`` / ``prod`` / ``None`` legacy) so the
    vectorstore + DB target reflect that env. Each env gets its own
    schema_vs (pointing at ``rag-schema-<env>``) and its own db_config
    (dev vs prod credentials) resolved via
    ``ask_llm_gateway.infrastructure.secrets.resolve_db_config`` (encrypted store).
    """

    # Keyed on (llm_revision, env). The bundle holds an LLM (and an executor
    # whose formatter wraps it) with the model baked into the ChatLiteLLM
    # constructor, so the revision must be part of the key — otherwise
    # switching the active LLM in ASK Setup has no effect until the process
    # restarts. See ``ask_llm_gateway.application.factory.llm_revision``.
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

            from ask_llm_gateway.application.factory import build_llm
            from ask_llm_gateway.infrastructure.secrets import resolve_db_config
            from ask_sql_executor.application.executor_service import SqlExecutorService
            from ask_sql_executor.application.result_formatter import LLMResultFormatter

            from .infrastructure.rag_service import init_vectorstores

            cfg = _load_settings()
            llm = build_llm(cfg)
            schema_vs, _docs_vs = init_vectorstores(cfg, env=env)
            # Per-env DB target from the encrypted store (2026-07 migration):
            # reads the ``db_dev`` / ``db_prod`` doc. ``prod`` never inherits ``dev``.
            db_type, db_config = resolve_db_config(env)
            bundle = {
                "llm": llm,
                "schema_vs": schema_vs,
                "db_type": db_type,
                "db_config": db_config,
                "hana_schema": (db_config or {}).get("schema", "") if db_type == "hana" else "",
                "schema_mode": cfg.get("schema_mode", "both"),
                "sql_executor": SqlExecutorService(formatter=LLMResultFormatter(llm)),
            }
            # Evict superseded revisions so a process that has seen several model
            # switches keeps at most one bundle per env.
            for stale in [k for k in cls._bundles if k[0] != revision]:
                del cls._bundles[stale]
            cls._bundles[key] = bundle
            return bundle

    def resolve(self, request: ResolutionRequest) -> IntentResolutionResult:
        from ask_sql_executor.domain.models import ExecutionRequest

        from .infrastructure.sql_service import generate_sql

        bundle = self._get_bundle(request.env)
        history = "\n".join(
            f"{turn.get('role', '?')}: {turn.get('content', '')}"
            for turn in (request.conversation_history or [])
        )

        started = time.monotonic()
        try:
            sql_result = generate_sql(
                request.question,
                bundle["schema_vs"],
                bundle["llm"],
                bundle["db_type"],
                history,
                bundle["schema_mode"],
                hana_schema=bundle.get("hana_schema", ""),
                # Workspace scope: restrict RAG chunks to the workspace's entities.
                allowed_ids=request.allowed_entity_ids,
                # Customer + workspace/business-domain framing (built by the
                # orchestrator, passed via organization_context). Precise/smart
                # get this through user_system_prompt / the entity selector;
                # flash builds SQL directly, so inject it into the prompt here.
                user_context=request.organization_context or "",
            )
        except Exception as exc:  # noqa: BLE001 — strategy boundary
            raise StrategyExecutionError(f"flash.generate_sql failed: {exc}") from exc

        if "error" in sql_result:
            return _empty_result(
                error=sql_result["error"],
                answer=f"Pipeline error: {sql_result['error']}",
                started=started,
            )

        sql = sql_result["sql"]
        try:
            formatted = bundle["sql_executor"].execute_and_format(
                ExecutionRequest(sql=sql, db_type=bundle["db_type"], db_config=bundle["db_config"]),
                question=request.question,
            )
        except Exception as exc:  # noqa: BLE001
            raise StrategyExecutionError(f"flash.execute_and_format failed: {exc}") from exc

        return IntentResolutionResult(
            plan={},  # Flash has no IR — chunk RAG goes straight from question to SQL
            yamls=[],  # nor explicit YAML resolution
            edges=[],
            disambiguation=None,
            error=formatted.error,
            trace=_trace(started, "flash"),
            sql=sql,
            rows=formatted.rows_dict if formatted.error is None else None,
            answer=formatted.answer,
        )


def _empty_result(*, error: str, answer: str, started: float) -> IntentResolutionResult:
    return IntentResolutionResult(
        plan={},
        yamls=[],
        edges=[],
        disambiguation=None,
        error=error,
        trace=_trace(started, "flash"),
        sql=None,
        rows=None,
        answer=answer,
    )
