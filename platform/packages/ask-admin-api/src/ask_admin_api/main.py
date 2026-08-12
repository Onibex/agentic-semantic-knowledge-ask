"""
ask_admin_api/main.py
─────────────────────────────────────────────────────────────────────────────
FastAPI entry point for the ASK Admin API.

Physically separate from ask-orchestrator (Plan J): the admin endpoints —
dictionary CRUD, embeddings ingestion, YAML ingestion — are consumed by the
admin SPA, run on a different pod, and have a different audience (admins vs
end-users) and SLA. Sharing only what the typed packages expose.

Default port: 8081 (vs ask-orchestrator's 8080). Override at deployment time.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .application.warmup import warmup_embedder_sync
from .auth.validator import require_role
from .logging_config import configure_logging
from .routers import (
    admin_config,
    admin_me,
    business_domains,
    contracts,
    dictionary,
    docs,
    embeddings,
    enrichment,
    health,
    ingest,
    ingest_config,
    internal,
    lifecycle,
    llm_config,
    mcp,
    organization,
    sap_connection,
    secrets,
    setup_effective,
    source_profiles,
    system_prompts,
    viz_admin,
    viz_conflicts,
    viz_ingest,
    viz_yamls,
    workspaces,
    yaml_ingestion,
)

# Wire structured logging before anything else creates loggers.
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI lifespan handler.

    Three boot duties:
      1. Validate the encrypted-secrets master key (fail-closed if missing
         or malformed). See HANDOFF §4.
      2. Validate the semantic-layer paths (REPO_ROOT / WORKSPACE_PATH) are
         set and point to a real directory with a git repo. Fails closed if
         missing — silent fallback to "." caused YAML commits to land in
         the code repo before the repo-split.
      3. Fire embedder warmup in a background thread so the first Publish
         doesn't pay the cold-start tax (model weights download, SAP AI Core
         credentials validation, etc.). The HTTP server starts serving
         immediately — warmup happens in parallel. Status is queryable at
         ``GET /v1/health/warmup``.
    """
    from ask_llm_gateway.infrastructure.secrets.crypto import validate_master_key

    try:
        validate_master_key()
        logger.info("ONIBEX_ENCRYPTION_KEY validated — encrypted secrets backend ready")
    except SystemExit as exc:
        logger.critical("Encrypted secrets boot check failed: %s", exc)
        raise

    _validate_semantic_layer_paths()
    _init_release_branches()

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, warmup_embedder_sync)
    logger.info("ask-admin-api ready; embedder warmup kicked off in background")
    yield
    logger.info("ask-admin-api shutting down")


def _init_release_branches() -> None:
    """Create the ``dev`` + ``prod`` git branches at boot if absent (audit §3.1).

    Best-effort — a failure (no repo, 0 commits) never blocks boot. Skipped
    under pytest so tests don't materialise branches in the code repo via
    GitPython's ``search_parent_directories`` climb.
    """
    import os

    from .config import get_settings

    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    repo_root = get_settings().repo_root
    if not repo_root:
        return
    try:
        from .application.git_service import GitService

        created = GitService(repo_root=repo_root).init_release_branches()
        if created:
            logger.info("Initialised release branches: %s", ", ".join(created))
    except Exception:  # noqa: BLE001 — never block boot on branch init
        logger.warning("init_release_branches at boot failed", exc_info=True)


def _validate_semantic_layer_paths() -> None:
    """Refuse to boot if REPO_ROOT / WORKSPACE_PATH are missing or invalid.

    Pre-split, the defaults were ``repo_root="."`` and
    ``workspace_path="workspace-ecc/ask"``. GitPython's
    ``search_parent_directories=True`` then climbed to the code repo's .git
    and YAML commits ended up mixed with code commits. The split moved YAMLs
    to a separate repo; this check makes sure the operator actually wired the
    env vars to that new repo and didn't leave the old behaviour active.

    Skipped under pytest — tests that touch the filesystem set the env vars
    themselves (see conftest); tests that don't need them (secrets, prompts)
    shouldn't be forced to invent a dummy semantic-layer path.
    """
    import os
    from pathlib import Path

    from .config import get_settings

    if os.getenv("PYTEST_CURRENT_TEST"):
        logger.debug("Skipping semantic-layer path validation under pytest")
        return

    s = get_settings()
    if not s.repo_root:
        raise SystemExit(
            "SEMANTIC_LAYER_PATHS_MISSING: REPO_ROOT is empty. "
            "Set REPO_ROOT (and WORKSPACE_PATH) in .env or the process "
            "environment to the absolute path of the semantic-layer git "
            "repo (e.g. REPO_ROOT=C:/Onibex/python/semantic-layer-s4h). "
            "See docs/runbooks/local-development.md §Pre-requisites."
        )
    if not s.workspace_path:
        raise SystemExit(
            "SEMANTIC_LAYER_PATHS_MISSING: WORKSPACE_PATH is empty. "
            "Set WORKSPACE_PATH in .env or the process environment "
            "(typically the same value as REPO_ROOT)."
        )
    repo_root = Path(s.repo_root).resolve()
    workspace = Path(s.workspace_path).resolve()
    if not repo_root.is_dir():
        raise SystemExit(f"SEMANTIC_LAYER_PATHS_INVALID: REPO_ROOT={repo_root} is not a directory.")
    if not workspace.is_dir():
        raise SystemExit(
            f"SEMANTIC_LAYER_PATHS_INVALID: WORKSPACE_PATH={workspace} is not a directory."
        )
    if not (repo_root / ".git").exists():
        # Warn but allow boot — the operator may be intentionally running
        # against a non-versioned snapshot (tests, scratch). GitService will
        # just no-op on commit attempts. With SEMANTIC_LAYER_AUTO_INIT=true
        # (the docker-compose default) `_init_release_branches` right after
        # this initialises the repo automatically, so the warning is
        # transient there.
        logger.warning(
            "SEMANTIC_LAYER_NO_GIT: %s has no .git — commits will be no-ops. "
            "Run `git init` in that directory, or set "
            "SEMANTIC_LAYER_AUTO_INIT=true to initialise it automatically. "
            "Without git, dev publish records no history and publish-to-prod "
            "FAILS.",
            repo_root,
        )
    logger.info(
        "Semantic layer paths validated: repo_root=%s workspace_path=%s",
        repo_root,
        workspace,
    )


app = FastAPI(
    title="ASK Admin API",
    version="0.1.0",
    description=(
        "Admin endpoints for the ASK Platform — dictionary CRUD, ingestion. "
        "Consumed by the admin SPA. Physically separate from "
        "ask-orchestrator (different pod, different SLA, different audience). "
        "Also exposes /v1/ingest/* for machine-to-machine producers (Kafka "
        "Connect HTTP Sink, Watson X webhooks) authenticated via X-API-Key."
    ),
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────────────────
# Error visibility (2026-07): FastAPI returns 4xx (422 validation, 400/409/…)
# to the client but does NOT log them, so operators saw "no docker log" while
# debugging e.g. a 422 on a structural entity edit. Log the informative ones
# with their detail, then delegate to FastAPI's DEFAULT handler so the response
# body + status + headers are byte-identical (no behaviour change). Routine
# 401/404 stay quiet to avoid noise.
# ─────────────────────────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def _log_request_validation(request: Request, exc: RequestValidationError):
    # Strip `input` from each error so request values (e.g. a password field on
    # admin_config) are never written to logs — keep only loc/msg/type.
    safe = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    logger.warning("422 request-validation on %s %s: %s", request.method, request.url.path, safe)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(StarletteHTTPException)
async def _log_http_exception(request: Request, exc: StarletteHTTPException):
    detail = str(getattr(exc, "detail", ""))[:800]
    if exc.status_code >= 500:
        logger.error("%s %s -> %s: %s", request.method, request.url.path, exc.status_code, detail)
    elif exc.status_code >= 400 and exc.status_code not in (401, 404):
        logger.warning("%s %s -> %s: %s", request.method, request.url.path, exc.status_code, detail)
    return await http_exception_handler(request, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Authorization (Iter SPA-AUTH Phase 1.3): the admin API is admin-only. Every
# router that reads or mutates configuration / secrets / the semantic layer is
# gated at include time with ``require_role("ask-admin")`` (a router-level
# dependency that runs before the endpoint). Kept OPEN (authenticated, any role)
# on purpose:
#   - health   : liveness, unauthenticated by design.
#   - admin_me : returns the caller's own token claims (identity display).
#   - internal : cache-reload trigger (server/ops-driven; see BACKLOG to gate).
#   - ingest   : M2M SAP-JSON push — authenticated by its OWN X-API-Key
#                dependency (verify_api_key), not a user bearer token. Adding a
#                bearer role-gate here would 401 the machine caller.
#   - workspaces: its GET list (``/v1/admin/workspaces``) is consumed by the
#                 chat SPA (ask-user) to scope queries; the write endpoints are
#                 gated per-endpoint inside workspaces.py instead.
_ADMIN_ONLY = [Depends(require_role("ask-admin"))]

app.include_router(health.router)
app.include_router(admin_me.router)
app.include_router(internal.router)
app.include_router(ingest.router)  # M2M: own X-API-Key auth (verify_api_key)
app.include_router(workspaces.router)  # GET open (chat scoping); writes gated in-router

app.include_router(admin_config.router, dependencies=_ADMIN_ONLY)
app.include_router(llm_config.router, dependencies=_ADMIN_ONLY)
app.include_router(contracts.router, dependencies=_ADMIN_ONLY)
app.include_router(docs.router, dependencies=_ADMIN_ONLY)
app.include_router(mcp.router, dependencies=_ADMIN_ONLY)
app.include_router(sap_connection.router, dependencies=_ADMIN_ONLY)
app.include_router(dictionary.router, dependencies=_ADMIN_ONLY)
app.include_router(yaml_ingestion.router, dependencies=_ADMIN_ONLY)
app.include_router(embeddings.router, dependencies=_ADMIN_ONLY)
app.include_router(
    viz_yamls.router, dependencies=_ADMIN_ONLY
)  # YAML Visualizer endpoints (/v1/viz/)
app.include_router(
    viz_ingest.router, dependencies=_ADMIN_ONLY
)  # SAP JSON merge engine (/v1/viz/ingest/sap-json)
app.include_router(
    viz_conflicts.router, dependencies=_ADMIN_ONLY
)  # Conflict list + resolve (/v1/viz/yamls/{id}/conflicts)
app.include_router(viz_admin.router, dependencies=_ADMIN_ONLY)  # Stats + export (/v1/viz/)
app.include_router(
    secrets.router, dependencies=_ADMIN_ONLY
)  # Encrypted secrets CRUD (/v1/admin/secrets/*)
app.include_router(
    system_prompts.router, dependencies=_ADMIN_ONLY
)  # Editable system prompts (/v1/admin/prompts/*)
app.include_router(
    enrichment.router, dependencies=_ADMIN_ONLY
)  # AI-assisted YAML enrichment (/v1/admin/enrich/*)
app.include_router(
    setup_effective.router, dependencies=_ADMIN_ONLY
)  # Read-only setup snapshot for the SPA
app.include_router(
    business_domains.router, dependencies=_ADMIN_ONLY
)  # Singleton Business Domain routes by ID
app.include_router(
    lifecycle.router, dependencies=_ADMIN_ONLY
)  # DP catalog + lifecycle rebuild (UX_CHANGES Iter 1)
app.include_router(organization.router, dependencies=_ADMIN_ONLY)  # Singleton organization profile
app.include_router(
    source_profiles.router, dependencies=_ADMIN_ONLY
)  # Source-system profiles for the DDL form (Phase C2)
app.include_router(
    ingest_config.router, dependencies=_ADMIN_ONLY
)  # Effective column-naming mode for the Manual-entity form
