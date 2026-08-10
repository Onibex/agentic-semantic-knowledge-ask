"""POST /v1/query — request flow.

  1. Classify the macro intent (LLM call).
  2. Dispatch by intent:
     - SQL_EXECUTION  → ResolveIntent → (Flash bypass OR SqlGeneration → executor)
     - SCHEMA_QUERY   → ask-schema-service
     - DOCS_QUERY     → ask-docs-service
     - ACTION_EXECUTION → ask-action-execution (SAP write ops via MCP)

For SQL_EXECUTION, the chain is:
  - Flash strategy returns sql/rows/answer directly — orchestrator skips
    SqlGenerationService.
  - Precise/Smart strategies return YAMLs+IR+edges only — orchestrator calls
    ask_sql_generation.FreeformSqlGenerator, then runs the SQL through
    ask-sql-executor.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ask_intent_resolution.application.resolve_intent_use_case import (
    get_default_use_case,
)
from ask_intent_resolution.domain.ports import ResolutionRequest
from ask_intent_resolution.domain.result import IntentResolutionResult
from ask_sql_executor.application.executor_service import SqlExecutorService
from ask_sql_executor.domain.models import ExecutionRequest
from ask_sql_generation.domain.models import SqlGenerationRequest

from ..auth.validator import TokenClaims, validate_token
from ..classification.macro_classifier import MacroIntentClassifier
from ..config import SettingsCache  # in-memory cache for config/settings.json
from ..models.requests import QueryRequest
from ..models.responses import Citation, ErrorResponse, MacroIntent, QueryResponse, TokensBreakdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["query"])

_classifier = MacroIntentClassifier()


def reset_singletons() -> list[str]:
    """Drop every cached singleton owned by this router so the next request
    rebuilds them from a fresh ``settings.json``. Called by the
    ``/v1/internal/reload`` endpoint after the admin UI saves config.

    Returns the names of singletons that were actually cleared (helpful for
    the reload response payload).
    """
    global _sql_gen_singletons, _sql_exec_singleton
    global _schema_singletons, _docs_singletons, _action_singleton
    cleared: list[str] = []
    for name, value in (
        ("sql_generator", _sql_gen_singletons),
        ("sql_executor", _sql_exec_singleton),
        ("schema_service", _schema_singletons),
        ("docs_service", _docs_singletons),
        ("action_service", _action_singleton),
    ):
        if value:  # truthy: a built object, or a non-empty per-env cache
            cleared.append(name)
    _sql_gen_singletons = {}
    _sql_exec_singleton = None
    _schema_singletons = {}
    _docs_singletons = {}
    _action_singleton = None
    # Drop the cached settings.json contents too — singletons rebuild from
    # whatever is on disk at next request.
    SettingsCache.invalidate()
    cleared.append("settings_cache")

    # Drain HANA connection pools so the next request picks up any DB
    # credential change. Pools live in the SQL executor package; importing
    # lazily keeps this router cheap and avoids pulling hdbcli at import.
    try:
        from ask_sql_executor.infrastructure.hana_pool import reset_hana_pools

        if reset_hana_pools() > 0:
            cleared.append("hana_pools")
    except Exception:  # noqa: BLE001 — best-effort reset
        logger.exception("hana pool drain failed during reset_singletons")

    return cleared


def _build_tokens_breakdown(summary: dict[str, Any]) -> TokensBreakdown | None:
    """Map TokenTracker.summary() to the Pydantic shape.

    Returns None only when the tracker captured nothing at all. In practice
    every request records at least one call, because macro classification is
    itself an LLM chain (``MacroIntentClassifier.classify``) — so even
    SCHEMA_QUERY, whose own handler is a pure OpenSearch lookup, reports the
    classifier call.
    """
    if (summary.get("total_calls") or 0) <= 0:
        return None
    return TokensBreakdown(
        total_calls=summary.get("total_calls", 0),
        input_tokens=summary.get("input_tokens", 0),
        output_tokens=summary.get("output_tokens", 0),
        total_tokens=summary.get("total_tokens", 0),
        by_phase=summary.get("by_phase", {}),
        records=summary.get("records", []),
    )


def _with_tokens(response: QueryResponse, tracker: Any) -> QueryResponse:
    """Attach the per-request tracker summary to ``response``.

    Called on EVERY return path out of ``run_query_pipeline`` — including the
    ACTION_EXECUTION branch, which used to return early and therefore always
    shipped ``tokens_used=None, tokens_breakdown=None``. The handler-supplied
    ``tokens_used`` is preserved as a fallback when the tracker saw no calls.
    """
    breakdown = _build_tokens_breakdown(tracker.summary())
    if breakdown is not None:
        response.tokens_breakdown = breakdown
        response.tokens_used = breakdown.total_tokens
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Lazy singletons — built on first use, thread-safe. Iter 4 added the
# SqlExecutorService here; the LLM Gateway promotion is still on hold while
# the colleague's package is fixed externally.
# ─────────────────────────────────────────────────────────────────────────────
_sql_gen_lock = threading.Lock()
# Keyed on (llm_revision, db_type).
#   db_type — not env: dev and prod may target different engines (multi-DB
#     registry) and the dialect prompt is a function of db_type, so envs sharing
#     an engine reuse the same generator.
#   llm_revision — the generator holds a ChatLiteLLM with the model baked into
#     its constructor. Without this key it would outlive an admin switching the
#     active LLM and pin the process to the old model until restart.
_sql_gen_singletons: dict[tuple[str, str], Any] = {}
_sql_exec_lock = threading.Lock()
# (llm_revision, service) — the formatter wraps an LLM, same reasoning as above.
_sql_exec_singleton: tuple[str, Any] | None = None
# Schema + docs services are cached PER publish-env (dev/prod/None) so a chat
# query reads the env the user selected, mirroring the strategy bundle caches.
_schema_lock = threading.Lock()
_schema_singletons: dict[Any, Any] = {}
_docs_lock = threading.Lock()
_docs_singletons: dict[Any, Any] = {}
_action_lock = threading.Lock()
_action_singleton: Any = None


def _get_sql_generator(env: str | None = None) -> Any:
    """Return the freeform SQL generator whose dialect matches ``env``'s engine.

    The active connection (and thus db_type) can differ per env, so the dialect
    prompt is resolved from ``env`` and the generator is cached per db_type —
    and per LLM revision, so switching the active LLM takes effect without a
    restart (see ``factory.llm_revision``).
    """
    from ask_llm_gateway.application.factory import llm_revision
    from ask_llm_gateway.infrastructure.secrets import resolve_db_config

    db_type, _ = resolve_db_config(env)
    revision = llm_revision()
    key = (revision, db_type)
    cached = _sql_gen_singletons.get(key)
    if cached is not None:
        return cached
    with _sql_gen_lock:
        cached = _sql_gen_singletons.get(key)
        if cached is not None:
            return cached
        from ask_llm_gateway.application.factory import build_llm
        from ask_sql_generation.application.sql_generator import FreeformSqlGenerator

        cfg = SettingsCache.get()
        llm = build_llm(cfg)
        gen = FreeformSqlGenerator(llm=llm, db_type=db_type)
        # Evict superseded revisions so a long-lived process holding many model
        # switches keeps at most one generator per db_type.
        for stale in [k for k in _sql_gen_singletons if k[0] != revision]:
            del _sql_gen_singletons[stale]
        _sql_gen_singletons[key] = gen
        return gen


def _get_sql_executor() -> SqlExecutorService:
    """Cached per LLM revision — the result formatter wraps an LLM."""
    global _sql_exec_singleton
    from ask_llm_gateway.application.factory import llm_revision

    revision = llm_revision()
    if _sql_exec_singleton is not None and _sql_exec_singleton[0] == revision:
        return _sql_exec_singleton[1]
    with _sql_exec_lock:
        if _sql_exec_singleton is not None and _sql_exec_singleton[0] == revision:
            return _sql_exec_singleton[1]
        from ask_llm_gateway.application.factory import build_llm
        from ask_sql_executor.application.result_formatter import LLMResultFormatter

        cfg = SettingsCache.get()
        llm = build_llm(cfg)
        service = SqlExecutorService(formatter=LLMResultFormatter(llm))
        _sql_exec_singleton = (revision, service)
        return service


def _get_docs_service(env: str | None = None) -> Any:
    """Build the DocsRagService once per env (reads ask-*-{env} docs index)."""
    cached = _docs_singletons.get(env)
    if cached is not None:
        return cached
    with _docs_lock:
        cached = _docs_singletons.get(env)
        if cached is not None:
            return cached
        from ask_docs_service.application.factory import build_default_docs_service

        svc = build_default_docs_service(env=env)
        _docs_singletons[env] = svc
        return svc


def _get_schema_service(env: str | None = None) -> Any:
    """Build the SchemaResolverService once per env (reads ask-*-{env} indices)."""
    cached = _schema_singletons.get(env)
    if cached is not None:
        return cached
    with _schema_lock:
        cached = _schema_singletons.get(env)
        if cached is not None:
            return cached
        from ask_schema_service.application.factory import build_default_schema_resolver

        svc = build_default_schema_resolver(env=env)
        _schema_singletons[env] = svc
        return svc


def _get_action_service() -> Any:
    """Build the ActionExecutionApplicationService once (Iter D-revised)."""
    global _action_singleton
    if _action_singleton is not None:
        return _action_singleton
    with _action_lock:
        if _action_singleton is not None:
            return _action_singleton
        from ask_action_execution.application.factory import build_default_action_service

        _action_singleton = build_default_action_service()
        return _action_singleton


def run_query_pipeline(req: QueryRequest, user: dict) -> QueryResponse:
    """Core pipeline: TokenTracker setup → macro classify → handler dispatch
    → tokens breakdown injection. Auth-agnostic so it can be reused by
    multiple front doors (the /v1/query router, the public /external/ask
    sub-app, future MCP shims, etc.). Each caller decides its own auth
    posture and passes a `user` dict for log correlation.
    """
    from ask_llm_gateway.infrastructure.token_tracker import (
        TokenTracker,
        clear_active_tracker,
        set_active_tracker,
        track_phase,
    )

    trace_id = uuid.uuid4().hex
    tracker = TokenTracker(query_id=trace_id)
    set_active_tracker(tracker)

    try:
        # Classify macro intent first so ACTION_EXECUTION can bypass the
        # workspace scope check (it talks to MCP, not the KG).
        with track_phase("macro_classification"):
            macro_intent: MacroIntent = _classifier.classify(req.question)

        # ACTION_EXECUTION: MCP write ops — no KG lookup, no workspace scope.
        if macro_intent == "ACTION_EXECUTION":
            logger.info(
                "query received",
                extra={
                    "trace_id": trace_id,
                    "mode": req.mode,
                    "macro_intent": macro_intent,
                    "session_id": req.session_id,
                    "workspace_id": req.workspace_id,
                    "user_email": user.get("email"),
                    "auth_bypass": user.get("bypass", False),
                },
            )
            try:
                return _with_tokens(_handle_action_execution(req, trace_id), tracker)
            except Exception as exc:  # noqa: BLE001
                logger.exception("ACTION_EXECUTION failed", extra={"trace_id": trace_id})
                raise HTTPException(
                    status_code=500,
                    detail=ErrorResponse(
                        error_code="PIPELINE_ERROR",
                        message=str(exc),
                        trace_id=trace_id,
                    ).model_dump(),
                )

        # Workspace scope (Iter 1, Req #5). The pipeline only sees entities
        # that belong to the active workspace — no cross-workspace queries.
        # Empty list = workspace has no DPs yet → block with 400.
        from ..workspace_scope import get_scope_provider

        # Env-gated scope (Option B): membership ∩ entities published to req.env.
        allowed_entity_ids = get_scope_provider().get_entity_ids(req.workspace_id, env=req.env)
        if allowed_entity_ids is None:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse(
                    error_code="WORKSPACE_NOT_FOUND",
                    message=f"Workspace '{req.workspace_id}' does not exist.",
                    trace_id=trace_id,
                ).model_dump(),
            )
        if not allowed_entity_ids:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error_code="WORKSPACE_HAS_NO_ENTITIES",
                    message=(
                        f"Workspace '{req.workspace_id}' has no entities published "
                        f"to the '{req.env}' environment. Add Data Products and "
                        f"publish their entities to {req.env} before querying."
                    ),
                    trace_id=trace_id,
                ).model_dump(),
            )

        logger.info(
            "query received",
            extra={
                "trace_id": trace_id,
                "mode": req.mode,
                "macro_intent": macro_intent,
                "session_id": req.session_id,
                "workspace_id": req.workspace_id,
                "scope_entity_count": len(allowed_entity_ids),
                "user_email": user.get("email"),
                "auth_bypass": user.get("bypass", False),
            },
        )

        try:
            if macro_intent == "SQL_EXECUTION":
                response = _handle_sql_execution(req, macro_intent, trace_id)
            elif macro_intent == "SCHEMA_QUERY":
                # Schema-plane scope (BACKLOG A/D1): membership ∪ composed_of
                # bronzes, so "describe VBAK" works when VBAK composes an
                # in-scope Silver. Superset of the (non-empty) gate value above,
                # so it is never None/[] here.
                schema_scope = get_scope_provider().get_schema_entity_ids(
                    req.workspace_id, env=req.env
                )
                response = _handle_schema_query(req, trace_id, schema_scope)
            elif macro_intent == "DOCS_QUERY":
                response = _handle_docs_query(req, trace_id)
            else:
                raise HTTPException(
                    status_code=500,
                    detail=ErrorResponse(
                        error_code="UNKNOWN_MACRO_INTENT",
                        message=f"Classifier returned unsupported intent {macro_intent!r}",
                        trace_id=trace_id,
                    ).model_dump(),
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — boundary error handling
            logger.exception("query failed", extra={"trace_id": trace_id})
            raise HTTPException(
                status_code=500,
                detail=ErrorResponse(
                    error_code="PIPELINE_ERROR",
                    message=str(exc),
                    trace_id=trace_id,
                ).model_dump(),
            )

        return _with_tokens(response, tracker)
    finally:
        clear_active_tracker()


@router.post(
    "/query",
    response_model=QueryResponse,
    responses={500: {"model": ErrorResponse}, 501: {"model": ErrorResponse}},
)
def query(
    req: QueryRequest,
    claims: TokenClaims = Depends(validate_token),
) -> QueryResponse:
    """Chat front door — multi-issuer JWT authenticated. Internal API for the chat SPA.

    Sync `def` (not `async def`) so FastAPI dispatches it to the Starlette
    thread pool. `run_query_pipeline` is blocking (HANA, OpenSearch, LLM HTTP),
    so keeping the endpoint `async def` would serialize every request on the
    event loop.
    """
    user = {"email": claims.email, "bypass": False, "roles": claims.roles}
    return run_query_pipeline(req, user)


def _handle_sql_execution(
    req: QueryRequest,
    macro_intent: MacroIntent,
    trace_id: str,
) -> QueryResponse:
    """SQL_EXECUTION branch — Resolve → SqlGen → exec.

    Flash strategy bypasses the chain (returns sql/rows/answer directly).
    Precise/Smart return YAMLs+IR+edges; orchestrator chains them through
    SqlGenerationService → SqlExecutorService.
    """
    # Per-environment DB guard. ``prod`` does NOT inherit the dev connection
    # (see resolve_db_config) — if the requested env has no DB configured in the
    # encrypted store, block with a clear message instead of silently querying
    # the wrong database. Covers all three modes (Flash/Precise/Smart) since
    # they all execute SQL downstream.
    from ask_llm_gateway.infrastructure.secrets import is_db_configured

    if not is_db_configured(req.env):
        return QueryResponse(
            answer=(
                f"No database is configured for the '{req.env}' environment. "
                f"Ask an administrator to set up the '{req.env}' database "
                f"connection in the admin app (Database settings)."
            ),
            rows=None,
            sql=None,
            macro_intent=macro_intent,
            mode_used=req.mode,
            trace_id=trace_id,
            tokens_used=0,
        )

    use_case = get_default_use_case()
    # Resolve workspace scope + org context once per request; pass downstream
    # so strategies filter their retrieval + prepend the customer profile to
    # their system prompts.
    from ..organization_context import get_organization_provider
    from ..workspace_context import get_workspace_context_provider
    from ..workspace_scope import get_scope_provider

    allowed_entity_ids = get_scope_provider().get_entity_ids(req.workspace_id, env=req.env)
    # Framing preamble for the system prompt: the customer profile (company /
    # SAP version) + the ACTIVE workspace and its business-domain descriptions
    # (what the scope is about). Combined once here and threaded through the
    # existing organization_context channel so precise, smart AND flash all see
    # it — replaces the dead pipeline_v2 descriptions that never reached a prompt.
    system_context = _join_context(
        get_organization_provider().get_context_text(),
        get_workspace_context_provider().get_context_text(req.workspace_id),
    )

    resolution = use_case.resolve(
        ResolutionRequest(
            question=req.question,
            mode=req.mode,
            session_id=req.session_id,
            conversation_history=req.conversation_history or [],
            allowed_entity_ids=allowed_entity_ids,
            organization_context=system_context,
            # UX_CHANGES Iter 4 — read cutover. The strategy picks the
            # env-suffixed OpenSearch indices (ask-*-dev / ask-*-prod) based
            # on this field; legacy un-suffixed indices are no longer used
            # by the orchestrator once the client sends an env.
            env=req.env,
        )
    )

    # Flash bypass — strategy already produced sql/rows/answer.
    if resolution.sql is not None or resolution.disambiguation is not None or resolution.error:
        return _build_response_from_resolution(resolution, req, macro_intent, trace_id)

    return _chain_sql_generation_and_executor(
        resolution, req, macro_intent, trace_id, system_context
    )


def _build_response_from_resolution(
    resolution: IntentResolutionResult,
    req: QueryRequest,
    macro_intent: MacroIntent,
    trace_id: str,
) -> QueryResponse:
    """Used by Flash + disambiguation + IR-resolution errors (no SQL chain)."""
    return QueryResponse(
        answer=resolution.answer or _fallback_answer(resolution),
        rows=resolution.rows,
        sql=resolution.sql,
        macro_intent=macro_intent,
        mode_used=req.mode,
        trace_id=trace_id,
        tokens_used=resolution.trace.tokens_used,
    )


def _join_context(*blocks: str | None) -> str | None:
    """Join non-empty system-prompt context blocks (org + workspace) with a
    blank line. Returns None when every block is empty so downstream prompt
    builders treat 'no context' uniformly."""
    parts = [b.strip() for b in blocks if b and b.strip()]
    return "\n\n".join(parts) if parts else None


def _fallback_answer(resolution: IntentResolutionResult) -> str:
    if resolution.disambiguation is not None:
        return resolution.disambiguation.message
    if resolution.error:
        return f"Pipeline error: {resolution.error}"
    return "No results."


def _chain_sql_generation_and_executor(
    resolution: IntentResolutionResult,
    req: QueryRequest,
    macro_intent: MacroIntent,
    trace_id: str,
    organization_context: str | None = None,
) -> QueryResponse:
    """Run SqlGenerationService over Precise/Smart resolution then execute."""
    # Per-environment DB target from the encrypted store (2026-07 migration).
    # The env comes from the QueryRequest (default ``'dev'``); ``resolve_db_config``
    # reads the ``db_dev`` / ``db_prod`` doc. ``prod`` never inherits ``dev``.
    from ask_llm_gateway.infrastructure.secrets import resolve_db_config

    db_type, db_config = resolve_db_config(req.env)
    # Generic schema/dataset hint carried in the (historically HANA-named)
    # `hana_schema` field. Each dialect's prompt decides how to render it
    # (HANA/Db2/Snowflake → "SCHEMA"."TABLE"; BigQuery → dataset; etc.).
    hana_schema = db_config.get("schema") or db_config.get("dataset") or ""

    yamls_raw = [doc.get("raw_yaml") or "" for doc in resolution.yamls]
    yamls_raw = [y for y in yamls_raw if y]

    if not yamls_raw:
        return QueryResponse(
            answer="Pipeline error: no schema context resolved for the question.",
            rows=None,
            sql=None,
            macro_intent=macro_intent,
            mode_used=req.mode,
            trace_id=trace_id,
            tokens_used=resolution.trace.tokens_used,
        )

    sql_request = SqlGenerationRequest(
        question=req.question,
        yamls=yamls_raw,
        db_type=db_type,  # type: ignore[arg-type]
        ir_hints=resolution.plan,
        edges=resolution.edges,
        resolved_paths=resolution.plan.get("resolved_paths", {})
        if isinstance(resolution.plan, dict)
        else {},
        hana_schema=hana_schema,
        # Customer profile (company / SAP version / portal) — prepended to the
        # SQL prompt so answers are framed for this customer's install. Resolved
        # once per request; previously dropped after the Smart entity selector.
        user_system_prompt=organization_context or "",
    )
    # Generator dialect must match the SAME env we resolved db_type/db_config
    # from above — dev and prod may target different engines.
    sql_result = _get_sql_generator(req.env).generate(sql_request)

    if sql_result.error or not sql_result.sql:
        return QueryResponse(
            answer=f"Pipeline error: {sql_result.error or 'no SQL produced'}",
            rows=None,
            sql=None,
            macro_intent=macro_intent,
            mode_used=req.mode,
            trace_id=trace_id,
            tokens_used=sql_result.tokens_used or resolution.trace.tokens_used,
        )

    formatted = _get_sql_executor().execute_and_format(
        ExecutionRequest(
            sql=sql_result.sql,
            db_type=db_type,
            db_config=db_config or {},
        ),
        question=req.question,
    )
    rows = formatted.rows_dict if formatted.error is None else None
    answer = formatted.answer

    return QueryResponse(
        answer=answer,
        rows=rows,
        sql=sql_result.sql,
        macro_intent=macro_intent,
        mode_used=req.mode,
        trace_id=trace_id,
        tokens_used=sql_result.tokens_used or resolution.trace.tokens_used,
    )


def _handle_schema_query(
    req: QueryRequest,
    trace_id: str,
    allowed_entity_ids: list[str] | None = None,
) -> QueryResponse:
    """SCHEMA_QUERY branch — routed to ask-schema-service.

    ``allowed_entity_ids`` = the schema-plane workspace scope (membership +
    ``composed_of`` bronzes). ``None`` keeps the legacy unscoped behaviour
    for non-workspace callers.
    """
    from ask_schema_service.domain.models import SchemaQuery

    response = _get_schema_service(req.env).answer(
        SchemaQuery(question=req.question, allowed_entity_ids=allowed_entity_ids)
    )
    return QueryResponse(
        answer=response.answer or (response.error or "No schema match."),
        rows=None,
        sql=None,
        macro_intent="SCHEMA_QUERY",
        mode_used=req.mode,
        trace_id=trace_id,
        tokens_used=None,
    )


def _handle_docs_query(
    req: QueryRequest,
    trace_id: str,
) -> QueryResponse:
    """DOCS_QUERY branch — routed to ask-docs-service."""
    from ask_docs_service.domain.models import DocsQuery

    response = _get_docs_service(req.env).answer(DocsQuery(question=req.question))
    answer = response.answer or (response.error or "No data products matched.")

    citations: list[Citation] | None = None
    if response.citations:
        citations = [
            Citation(entity_id=c.entity_id, snippet=c.snippet, score=c.score)
            for c in response.citations
        ]
        # Append a compact Markdown footer for clients that render `answer`
        # directly. Structured `citations` is the canonical field; the footer
        # is retained for backward compatibility until UI consumers switch.
        cites = "\n\n---\n**Sources**:\n" + "\n".join(
            f"- `{c.entity_id}` ({c.score:.2f})" for c in response.citations
        )
        answer = answer + cites
    return QueryResponse(
        answer=answer,
        rows=None,
        sql=None,
        macro_intent="DOCS_QUERY",
        mode_used=req.mode,
        trace_id=trace_id,
        tokens_used=None,
        citations=citations,
    )


def _handle_action_execution(
    req: QueryRequest,
    trace_id: str,
) -> QueryResponse:
    """ACTION_EXECUTION branch — routed to ask-action-execution (MCP-backed)."""
    from ask_action_execution.domain.models import ActionRequest

    result = _get_action_service().execute(ActionRequest(question=req.question))
    return QueryResponse(
        answer=result.answer,
        rows=None,
        sql=None,
        macro_intent="ACTION_EXECUTION",
        mode_used=req.mode,
        trace_id=trace_id,
        tokens_used=None,
    )
