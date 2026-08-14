"""``/v1/admin/secrets/...`` — encrypted secrets management (LLM + Embedder).

This is the **canonical** path for provider credentials. Replaces the legacy
``/v1/admin/llm/config`` (which wrote plain text to ``settings.json``).

Storage backend: ``ask-system-settings-v1`` index in OpenSearch, with
Fernet-encrypted sensitive fields.

Endpoints
─────────
GET    /v1/admin/secrets/llm         masked view of stored LLM config
GET    /v1/admin/secrets/embedder    masked view of stored Embedder config
PUT    /v1/admin/secrets/llm         upsert LLM config (provider + fields)
PUT    /v1/admin/secrets/embedder    upsert Embedder config
POST   /v1/admin/secrets/test        probe the active LLM or Embedder
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from opensearchpy.exceptions import OpenSearchException

from ask_llm_gateway.infrastructure.secrets import (
    LLM_ACTIVE_POINTER_ID,
    SecretsRepository,
    db_provider_fields,
    get_secrets_provider,
    known_db_types,
    new_connection_id,
    new_llm_connection_id,
    provider_fields,
)
from ask_llm_gateway.infrastructure.secrets.registry import known_providers

from ..auth.validator import TokenClaims, validate_token
from ..config import get_settings
from ..models.secrets import (
    DbActivePutRequest,
    DbActiveView,
    DbConnectionDeleteResponse,
    DbConnectionsListResponse,
    DbConnectionTestResponse,
    DbConnectionUpsertRequest,
    DbConnectionView,
    DbProviderFieldSpec,
    DbProvidersListResponse,
    DbProviderSpec,
    DbSecretsDeleteResponse,
    DbSecretsGetResponse,
    DbSecretsPutRequest,
    LlmActivePutRequest,
    LlmActiveView,
    LlmConnectionDeleteResponse,
    LlmConnectionsListResponse,
    LlmConnectionTestResponse,
    LlmConnectionUpsertRequest,
    LlmConnectionView,
    ProviderFieldSpec,
    ProvidersListResponse,
    ProviderSpec,
    SecretsFieldView,
    SecretsGetResponse,
    SecretsPutRequest,
    SecretsTarget,
    SecretsTestRequest,
    SecretsTestResponse,
)


def _notify_orchestrator_reload(trace_id: str) -> None:
    """Fire-and-forget POST to the orchestrator's /v1/internal/reload.

    Clears the orchestrator's LLM singleton so the next /v1/query call picks up
    the new credentials immediately rather than after the 60-second TTL.  Runs
    in a daemon thread so it never blocks the secrets PUT response.
    """
    url = get_settings().ask_orchestrator_url
    if not url:
        return

    def _post() -> None:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.post(f"{url}/v1/internal/reload")
            logger.info("[%s] orchestrator reload → HTTP %s", trace_id, resp.status_code)
        except Exception:  # noqa: BLE001
            logger.warning("[%s] orchestrator reload failed (non-fatal)", trace_id, exc_info=True)

    threading.Thread(target=_post, daemon=True).start()


# Display labels mirror setup_effective._PROVIDER_LABELS — keep this single map.
_PROVIDER_LABELS: dict[str, str] = {
    "sap_aicore": "SAP AI Core",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "azure": "Azure OpenAI",
    "databricks": "Databricks",
    "bedrock": "AWS Bedrock",
    "vertex_ai": "Google Vertex AI",
    "huggingface": "Hugging Face (local)",
}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/secrets", tags=["admin/secrets"])


# Singleton — heavy to build (OpenSearch client). One instance per process.
_REPO: SecretsRepository | None = None


def _repo() -> SecretsRepository:
    global _REPO
    if _REPO is None:
        _REPO = SecretsRepository()
    return _REPO


# ── Provider metadata ────────────────────────────────────────────────────────


@router.get("/providers", response_model=ProvidersListResponse)
async def list_providers(
    _claims: TokenClaims = Depends(validate_token),
) -> ProvidersListResponse:
    """Return every provider the registry knows about + its declared fields.

    The SPA fetches this once on mount to render the right form per provider
    selection. Single source of truth — the same registry the runtime uses.
    """
    specs: list[ProviderSpec] = []
    for pid in known_providers():
        fields = [
            ProviderFieldSpec(name=fname, sensitive=sensitive)
            for fname, sensitive in provider_fields(pid)
        ]
        specs.append(
            ProviderSpec(
                id=pid,
                label=_PROVIDER_LABELS.get(pid, pid.replace("_", " ").title()),
                fields=fields,
            )
        )
    return ProvidersListResponse(providers=specs)


# ── GET ─────────────────────────────────────────────────────────────────────


def _build_masked_view(target: SecretsTarget, raw: dict[str, Any] | None) -> SecretsGetResponse:
    """Convert a raw OS doc into the masked GET response.

    For each field the provider's registry declares, surface a row showing
    either the stored plain value or ``"***"`` (when encrypted) or empty
    (when unset). Unknown providers (no registry entry) fall back to listing
    whatever keys are stored in ``plain`` + ``encrypted``.
    """
    if raw is None:
        return SecretsGetResponse(target=target, provider="", model="", fields=[])

    provider = str(raw.get("provider") or "")
    plain = dict(raw.get("plain") or {})
    encrypted = dict(raw.get("encrypted") or {})

    registry_entries = provider_fields(provider)
    rows: list[SecretsFieldView] = []

    if registry_entries:
        for name, sensitive in registry_entries:
            if sensitive:
                stored = name in encrypted
                rows.append(
                    SecretsFieldView(
                        name=name,
                        value="***" if stored else "",
                        sensitive=True,
                        source="encrypted" if stored else "default",
                    )
                )
            else:
                value = plain.get(name, "")
                rows.append(
                    SecretsFieldView(
                        name=name,
                        value=str(value),
                        sensitive=False,
                        source="plain" if value else "default",
                    )
                )
    else:
        # Unknown provider — show stored keys as-is so the admin can still
        # see what got migrated and decide.
        for name, value in plain.items():
            rows.append(
                SecretsFieldView(
                    name=str(name),
                    value=str(value),
                    sensitive=False,
                    source="plain",
                )
            )
        for name in encrypted:
            rows.append(
                SecretsFieldView(
                    name=str(name),
                    value="***",
                    sensitive=True,
                    source="encrypted",
                )
            )

    return SecretsGetResponse(
        target=target,
        provider=provider,
        model=str(raw.get("model") or ""),
        fields=rows,
        updated_at=str(raw.get("updated_at") or ""),
        updated_by=str(raw.get("updated_by") or ""),
    )


@router.get("/llm", response_model=SecretsGetResponse)
async def get_llm_secrets(
    _claims: TokenClaims = Depends(validate_token),
) -> SecretsGetResponse:
    return _build_masked_view("llm", _safe_get_raw("llm"))


@router.get("/embedder", response_model=SecretsGetResponse)
async def get_embedder_secrets(
    _claims: TokenClaims = Depends(validate_token),
) -> SecretsGetResponse:
    return _build_masked_view("embedder", _safe_get_raw("embedder"))


def _safe_get_raw(target: SecretsTarget) -> dict[str, Any] | None:
    try:
        return _repo().get_raw(target)
    except OpenSearchException as exc:
        logger.error("OpenSearch unavailable while reading %s secrets: %s", target, exc)
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: OpenSearch is not reachable.",
        ) from exc


# ── PUT ─────────────────────────────────────────────────────────────────────


@router.put("/llm", response_model=SecretsGetResponse)
async def put_llm_secrets(
    body: SecretsPutRequest,
    claims: TokenClaims = Depends(validate_token),
) -> SecretsGetResponse:
    return _do_upsert("llm", body, claims)


@router.put("/embedder", response_model=SecretsGetResponse)
async def put_embedder_secrets(
    body: SecretsPutRequest,
    claims: TokenClaims = Depends(validate_token),
) -> SecretsGetResponse:
    return _do_upsert("embedder", body, claims)


def _do_upsert(
    target: SecretsTarget, body: SecretsPutRequest, claims: TokenClaims
) -> SecretsGetResponse:
    trace_id = uuid.uuid4().hex
    user = getattr(claims, "email", None) or "anonymous"
    logger.info(
        "[%s] secrets put target=%s provider=%s user=%s",
        trace_id,
        target,
        body.provider,
        user,
    )

    try:
        stored = _repo().upsert(
            target,
            provider=body.provider,
            model=body.model,
            fields=body.fields,
            updated_by=user,
        )
    except OpenSearchException as exc:
        logger.error("[%s] OpenSearch write failed: %s", trace_id, exc)
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not persist secret.",
        ) from exc

    # Drop the cached entry on the runtime singleton so the next /v1/query
    # call picks up the new config without waiting for the 60s TTL.
    try:
        get_secrets_provider().invalidate(target)
    except Exception:  # noqa: BLE001 — best-effort cache eviction
        logger.warning("[%s] cache invalidation failed (non-fatal)", trace_id, exc_info=True)

    # Tell the orchestrator (separate process) to rebuild its LLM singleton.
    _notify_orchestrator_reload(trace_id)

    return _build_masked_view(target, stored)


# ── POST /test ──────────────────────────────────────────────────────────────


@router.post("/test", response_model=SecretsTestResponse)
async def test_secrets(
    body: SecretsTestRequest,
    claims: TokenClaims = Depends(validate_token),
) -> SecretsTestResponse:
    """Probe the active LLM or Embedder using the currently stored secrets.

    Reads from the SecretsProvider (cache + OpenSearch), seeds os.environ,
    and runs a tiny invocation. Returns latency + a friendly error message.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "[%s] secrets test target=%s user=%s",
        trace_id,
        body.target,
        getattr(claims, "email", "?"),
    )

    raw = _safe_get_raw(body.target)
    if raw is None:
        return SecretsTestResponse(
            success=False,
            target=body.target,
            provider="",
            model="",
            latency_ms=0,
            detail="No secrets stored for this target — save a provider config first.",
            error="NOT_CONFIGURED",
        )

    provider = str(raw.get("provider") or "")
    model = str(raw.get("model") or "")

    # The factory will re-read from SecretsProvider when build_llm /
    # build_embedder hits the LiteLLM path. Force a fresh fetch so the test
    # doesn't accidentally use a cached pre-write view.
    secrets_provider = get_secrets_provider()
    secrets_provider.invalidate(body.target)

    started = time.monotonic()
    try:
        secrets_provider.export_to_env(body.target)
        from ask_llm_gateway.application.factory import build_embedder, build_llm

        # build_* read from settings.json for the non-secret bits (stack_mode,
        # sap_ai_core.config_path); pass an empty dict — env vars seeded above
        # override anything that would have come from a file section anyway.
        if body.target == "llm":
            llm = build_llm({})
            llm.invoke("Reply with the single word ok")
            detail = "LLM responded"
        else:
            embedder = build_embedder({})
            vec = embedder.embed_query("ok")
            detail = f"Embedder returned {len(vec)}-dim vector"

        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info("[%s] secrets test ok %dms", trace_id, latency_ms)
        return SecretsTestResponse(
            success=True,
            target=body.target,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        latency_ms = int((time.monotonic() - started) * 1000)
        msg = str(exc)
        if "Give Feedback / Get Help" in msg:
            msg = msg.split("Give Feedback / Get Help")[0].strip()
        if len(msg) > 500:
            msg = msg[:500] + "..."
        logger.warning("[%s] secrets test failed: %s", trace_id, msg)
        return SecretsTestResponse(
            success=False,
            target=body.target,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            detail="Test failed — see error",
            error=msg,
        )


# ── DB config secrets (per-environment: dev / prod) — 2026-07 migration ──────
#
# The DB-config plane lives in the SAME ``ask-system-settings-v1`` index under
# targets ``db_dev`` / ``db_prod``. Connection testing stays client-side in the
# setup SPA Database page (admin-api has no DB drivers) — these endpoints only
# store / read / clear the (encrypted) config.


_VALID_DB_ENVS: frozenset[str] = frozenset({"dev", "prod"})

# Display labels for the DB backends — mirrors the SPA engine picker. Keep in
# sync when adding a backend to the DB registry.
_DB_LABELS: dict[str, str] = {
    "postgresql": "PostgreSQL",
    "hana": "SAP HANA",
    "snowflake": "Snowflake",
    "databricks": "Databricks",
    "bigquery": "BigQuery",
    "clickhouse": "ClickHouse",
    "sqlserver": "SQL Server",
    "db2": "IBM Db2",
    "fabric": "Microsoft Fabric",
    "presto": "Presto",
}


def _db_target(env: str) -> str:
    if env not in _VALID_DB_ENVS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown env {env!r} — expected one of {sorted(_VALID_DB_ENVS)}",
        )
    return f"db_{env}"


def _mask_db_rows(
    db_type: str, plain: dict[str, Any], encrypted: dict[str, Any]
) -> list[SecretsFieldView]:
    """Mask a stored DB doc's fields per the DB registry.

    Sensitive fields are returned BLANK (never the ciphertext); ``source`` is
    ``encrypted`` when a value is stored so the form shows a "keep current"
    placeholder. Plain fields carry their real values.
    """
    rows: list[SecretsFieldView] = []
    for name, sensitive, _kind in db_provider_fields(db_type):
        if sensitive:
            stored = name in encrypted
            rows.append(
                SecretsFieldView(
                    name=name,
                    value="",  # never leak ciphertext; form re-enters to change
                    sensitive=True,
                    source="encrypted" if stored else "default",
                )
            )
        else:
            value = plain.get(name, "")
            rows.append(
                SecretsFieldView(
                    name=name,
                    value=str(value),
                    sensitive=False,
                    source="plain" if value != "" else "default",
                )
            )
    return rows


def _coerce_db_fields(db_type: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Coerce string-stored fields to native types (port→int, bool flags) for
    the connection probe, mirroring the runtime resolver's coercion."""
    kinds = {name: kind for name, _sensitive, kind in db_provider_fields(db_type)}
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if value in (None, ""):
            continue
        kind = kinds.get(key, "str")
        if kind == "int":
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                out[key] = value
        elif kind == "bool":
            out[key] = str(value).strip().lower() in ("1", "true", "yes", "on")
        else:
            out[key] = value
    return out


def _build_db_masked_view(env: str, raw: dict[str, Any] | None) -> DbSecretsGetResponse:
    """Convert a raw ``db_{env}`` doc into the masked GET response."""
    if raw is None:
        return DbSecretsGetResponse(env=env, db_type="", fields=[], configured=False)  # type: ignore[arg-type]

    db_type = str(raw.get("provider") or "")
    plain = dict(raw.get("plain") or {})
    encrypted = dict(raw.get("encrypted") or {})
    rows = _mask_db_rows(db_type, plain, encrypted)
    configured = bool(db_type) and (bool(plain) or bool(encrypted))
    return DbSecretsGetResponse(
        env=env,  # type: ignore[arg-type]
        db_type=db_type,
        fields=rows,
        configured=configured,
        updated_at=str(raw.get("updated_at") or ""),
        updated_by=str(raw.get("updated_by") or ""),
    )


# ── DB connection registry (multi-DB, 2026-07) ───────────────────────────────
#
# NOTE: these literal-path routes (/db/providers, /db/connections, /db/active)
# are declared BEFORE the parametric /db/{env} routes below so FastAPI does not
# match "providers"/"connections"/"active" as an env value.


def _build_db_connection_view(cid: str, raw: dict[str, Any]) -> DbConnectionView:
    """Masked view of one registry connection doc (id + name + masked fields)."""
    db_type = str(raw.get("provider") or "")
    plain = dict(raw.get("plain") or {})
    encrypted = dict(raw.get("encrypted") or {})
    configured = bool(db_type) and (bool(plain) or bool(encrypted))
    return DbConnectionView(
        id=cid,
        name=str(raw.get("name") or ""),
        db_type=db_type,
        fields=_mask_db_rows(db_type, plain, encrypted),
        configured=configured,
        updated_at=str(raw.get("updated_at") or ""),
        updated_by=str(raw.get("updated_by") or ""),
    )


def _maybe_import_legacy_connections(user: str) -> None:
    """One-time migration: turn the legacy ``db_dev`` / ``db_prod`` singleton
    docs into registry connections + set them active, then drop the legacy docs.

    Runs only when the registry is empty (guarded by the caller). Copies the raw
    doc so the Fernet ciphertext is preserved (no decrypt/re-encrypt round-trip).
    """
    active: dict[str, str | None] = {}
    imported: list[str] = []
    for env in ("dev", "prod"):
        raw = _safe_get_raw(f"db_{env}")  # type: ignore[arg-type]
        if not raw or not raw.get("provider"):
            continue
        cid = new_connection_id()
        db_type = str(raw.get("provider"))
        doc = dict(raw)
        doc["name"] = f"{_DB_LABELS.get(db_type, db_type)} ({env})"
        doc["kind"] = "db_connection"
        _repo().upsert_raw(cid, doc)
        active[env] = cid
        imported.append(cid)
    if not imported:
        return
    _repo().set_active(active, updated_by=user)
    for env in ("dev", "prod"):
        try:
            _repo().delete(f"db_{env}")  # type: ignore[arg-type]
        except OpenSearchException:
            logger.warning("legacy db_%s delete after import failed (non-fatal)", env)
    try:
        sp = get_secrets_provider()
        sp.invalidate("db_active")
        sp.invalidate("db_dev")
        sp.invalidate("db_prod")
        for cid in imported:
            sp.invalidate(cid)
    except Exception:  # noqa: BLE001
        logger.warning("cache invalidation after legacy import failed", exc_info=True)
    logger.info("Imported %d legacy DB connection(s) into the registry", len(imported))


@router.get("/db/providers", response_model=DbProvidersListResponse)
async def list_db_providers(
    _claims: TokenClaims = Depends(validate_token),
) -> DbProvidersListResponse:
    """Return every DB backend + its declared connection fields.

    Drives the SPA's dynamic connection form. Same registry the runtime uses —
    adding a backend needs no SPA change.
    """
    specs: list[DbProviderSpec] = []
    for db_type in known_db_types():
        fields = [
            DbProviderFieldSpec(name=fname, sensitive=sensitive, kind=kind)
            for fname, sensitive, kind in db_provider_fields(db_type)
        ]
        specs.append(
            DbProviderSpec(
                id=db_type,
                label=_DB_LABELS.get(db_type, db_type.replace("_", " ").title()),
                fields=fields,
            )
        )
    return DbProvidersListResponse(providers=specs)


@router.get("/db/connections", response_model=DbConnectionsListResponse)
async def list_db_connections(
    claims: TokenClaims = Depends(validate_token),
) -> DbConnectionsListResponse:
    """List every registered connection + the active-per-env pointer.

    On first call with an empty registry, imports any legacy ``db_dev`` /
    ``db_prod`` docs so the upgrade is seamless.
    """
    user = getattr(claims, "email", None) or "anonymous"
    try:
        conns = _repo().list_db_connections()
        if not conns:
            _maybe_import_legacy_connections(user)
            conns = _repo().list_db_connections()
        active = _repo().get_active()
    except OpenSearchException as exc:
        logger.error("OpenSearch unavailable listing db connections: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: OpenSearch is not reachable.",
        ) from exc
    return DbConnectionsListResponse(
        connections=[_build_db_connection_view(cid, raw) for cid, raw in conns],
        active=DbActiveView(dev=active.get("dev"), prod=active.get("prod")),
    )


@router.post("/db/connections", response_model=DbConnectionView)
async def create_db_connection(
    body: DbConnectionUpsertRequest,
    claims: TokenClaims = Depends(validate_token),
) -> DbConnectionView:
    user = getattr(claims, "email", None) or "anonymous"
    cid = new_connection_id()
    try:
        stored = _repo().upsert(
            cid,
            provider=body.db_type,
            model="",
            fields=body.fields,
            updated_by=user,
            extra={"name": body.name, "kind": "db_connection"},
        )
    except OpenSearchException as exc:
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not create connection.",
        ) from exc
    _invalidate(cid)
    return _build_db_connection_view(cid, stored)


@router.put("/db/connections/active", response_model=DbActiveView)
async def set_db_active(
    body: DbActivePutRequest,
    claims: TokenClaims = Depends(validate_token),
) -> DbActiveView:
    """Set the active connection per environment (full desired state).

    Each id must reference an existing connection (or be null to clear the slot).
    """
    user = getattr(claims, "email", None) or "anonymous"
    for env, cid in (("dev", body.dev), ("prod", body.prod)):
        if cid and _safe_get_raw(cid) is None:  # type: ignore[arg-type]
            raise HTTPException(
                status_code=400,
                detail=f"Connection {cid!r} for env {env!r} does not exist.",
            )
    try:
        result = _repo().set_active({"dev": body.dev, "prod": body.prod}, updated_by=user)
    except OpenSearchException as exc:
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not update active connection.",
        ) from exc
    _invalidate("db_active")
    # _invalidate only evicts THIS process's read cache. The orchestrator is a
    # different container whose SecretsProvider caches the db_active pointer +
    # connection docs (60 s TTL), so switching the database from the UI appeared
    # to do nothing until the TTL expired — the exact bug the LLM registry
    # endpoints had before they gained this call. Best-effort by design.
    _notify_orchestrator_reload(uuid.uuid4().hex)
    return DbActiveView(dev=result.get("dev"), prod=result.get("prod"))


@router.put("/db/connections/{cid}", response_model=DbConnectionView)
async def update_db_connection(
    cid: str,
    body: DbConnectionUpsertRequest,
    claims: TokenClaims = Depends(validate_token),
) -> DbConnectionView:
    user = getattr(claims, "email", None) or "anonymous"
    if _safe_get_raw(cid) is None:  # type: ignore[arg-type]
        raise HTTPException(status_code=404, detail=f"Connection {cid!r} not found.")
    try:
        stored = _repo().upsert(
            cid,
            provider=body.db_type,
            model="",
            fields=body.fields,
            updated_by=user,
            preserve_blank_secrets=True,
            extra={"name": body.name, "kind": "db_connection"},
        )
        # Editing the ACTIVE connection changes what the orchestrator queries
        # (host, database, final, credentials) — same cross-container
        # invalidation as update_llm_connection.
        if cid in _repo().get_active().values():
            _notify_orchestrator_reload(uuid.uuid4().hex)
    except OpenSearchException as exc:
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not update connection.",
        ) from exc
    _invalidate(cid)
    return _build_db_connection_view(cid, stored)


@router.delete("/db/connections/{cid}", response_model=DbConnectionDeleteResponse)
async def delete_db_connection(
    cid: str,
    claims: TokenClaims = Depends(validate_token),
) -> DbConnectionDeleteResponse:
    """Delete a connection. If it was active for an env, that slot is cleared."""
    user = getattr(claims, "email", None) or "anonymous"
    try:
        active = _repo().get_active()
        deleted = _repo().delete(cid)  # type: ignore[arg-type]
        if active.get("dev") == cid or active.get("prod") == cid:
            new_active: dict[str, str | None] = {
                "dev": None if active.get("dev") == cid else active.get("dev"),
                "prod": None if active.get("prod") == cid else active.get("prod"),
            }
            _repo().set_active(new_active, updated_by=user)
            _invalidate("db_active")
            # Deleting the active connection leaves that env with NO database —
            # the orchestrator must see it now, not after the 60 s TTL.
            _notify_orchestrator_reload(uuid.uuid4().hex)
    except OpenSearchException as exc:
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not delete connection.",
        ) from exc
    _invalidate(cid)
    return DbConnectionDeleteResponse(id=cid, deleted=deleted)


@router.post("/db/connections/{cid}/test", response_model=DbConnectionTestResponse)
async def test_db_connection(
    cid: str,
    _claims: TokenClaims = Depends(validate_token),
) -> DbConnectionTestResponse:
    """Probe a stored connection using the exact code path the chat uses.

    Runs a trivial query through ask-sql-executor's adapter for the connection's
    engine. Requires the matching DB driver to be installed in this deployment;
    a missing driver returns a clear, non-fatal error.
    """
    raw = _safe_get_raw(cid)  # type: ignore[arg-type]
    if raw is None or not raw.get("provider"):
        raise HTTPException(status_code=404, detail=f"Connection {cid!r} not found.")
    db_type = str(raw.get("provider"))

    try:
        resolved = _repo().get_resolved(cid)  # type: ignore[arg-type]
    except PermissionError:
        return DbConnectionTestResponse(
            id=cid,
            success=False,
            db_type=db_type,
            latency_ms=0,
            detail="Cannot decrypt stored credentials",
            error="ENCRYPTION_KEY_MISMATCH",
        )
    config = _coerce_db_fields(db_type, dict((resolved or {}).get("fields") or {}))

    try:
        from ask_sql_executor.infrastructure.db_utils import test_connection as _db_probe
    except Exception as exc:  # noqa: BLE001 — driver/module not present in this image
        return DbConnectionTestResponse(
            id=cid,
            success=False,
            db_type=db_type,
            latency_ms=0,
            detail="Connection testing is not available in this deployment",
            error=f"DB drivers not installed: {exc}",
        )

    started = time.monotonic()
    try:
        ok, message = _db_probe(db_type, config)
    except Exception as exc:  # noqa: BLE001 — boundary
        latency_ms = int((time.monotonic() - started) * 1000)
        return DbConnectionTestResponse(
            id=cid,
            success=False,
            db_type=db_type,
            latency_ms=latency_ms,
            detail="Test failed — see error",
            error=str(exc)[:500],
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    return DbConnectionTestResponse(
        id=cid,
        success=ok,
        db_type=db_type,
        latency_ms=latency_ms,
        detail=message if ok else "Test failed — see error",
        error=None if ok else message,
    )


def _invalidate(target: str) -> None:
    """Best-effort eviction of the runtime cache for one target."""
    try:
        get_secrets_provider().invalidate(target)
    except Exception:  # noqa: BLE001
        logger.warning("cache invalidation failed for %s (non-fatal)", target, exc_info=True)


@router.get("/db/{env}", response_model=DbSecretsGetResponse)
async def get_db_secrets(
    env: str,
    _claims: TokenClaims = Depends(validate_token),
) -> DbSecretsGetResponse:
    target = _db_target(env)
    return _build_db_masked_view(env, _safe_get_raw(target))  # type: ignore[arg-type]


@router.put("/db/{env}", response_model=DbSecretsGetResponse)
async def put_db_secrets(
    env: str,
    body: DbSecretsPutRequest,
    claims: TokenClaims = Depends(validate_token),
) -> DbSecretsGetResponse:
    target = _db_target(env)
    trace_id = uuid.uuid4().hex
    user = getattr(claims, "email", None) or "anonymous"
    logger.info(
        "[%s] db secrets put env=%s db_type=%s user=%s",
        trace_id,
        env,
        body.db_type,
        user,
    )
    try:
        stored = _repo().upsert(
            target,  # type: ignore[arg-type]
            provider=body.db_type,
            model="",
            fields=body.fields,
            updated_by=user,
            preserve_blank_secrets=True,
        )
    except OpenSearchException as exc:
        logger.error("[%s] OpenSearch write failed: %s", trace_id, exc)
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not persist DB config.",
        ) from exc

    try:
        get_secrets_provider().invalidate(target)
    except Exception:  # noqa: BLE001 — best-effort cache eviction
        logger.warning("[%s] cache invalidation failed (non-fatal)", trace_id, exc_info=True)

    return _build_db_masked_view(env, stored)


@router.delete("/db/{env}", response_model=DbSecretsDeleteResponse)
async def delete_db_secrets(
    env: str,
    _claims: TokenClaims = Depends(validate_token),
) -> DbSecretsDeleteResponse:
    """Clear the env's DB config (e.g. prod left blank = 'not in use')."""
    target = _db_target(env)
    try:
        deleted = _repo().delete(target)  # type: ignore[arg-type]
    except OpenSearchException as exc:
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not delete DB config.",
        ) from exc
    try:
        get_secrets_provider().invalidate(target)
    except Exception:  # noqa: BLE001
        logger.warning("db secrets delete cache invalidation failed", exc_info=True)
    return DbSecretsDeleteResponse(env=env, deleted=deleted)  # type: ignore[arg-type]


# ── LLM connection registry (multi-LLM, SINGLE active — 2026-07) ──────────────
#
# N named LLM connections + a single-valued ``llm_active`` pointer (one global
# active LLM, NO dev/prod). Activating / editing-the-active / deleting-the-active
# PROJECTS the active connection into the canonical ``llm`` doc the runtime reads
# (``factory.build_llm``), so the hot path is unchanged. Provider field specs
# come from the SHARED ``GET /providers`` endpoint. Design ref: internal design
# doc (ITERATION_LLM_PROVIDERS_REGISTRY_PLAN).
#
# NOTE: literal-path routes (/llm/connections, /llm/connections/active) are
# declared BEFORE the parametric /llm/connections/{cid} routes so FastAPI does
# not match "active" as a cid.


def _mask_llm_rows(
    provider: str, plain: dict[str, Any], encrypted: dict[str, Any]
) -> list[SecretsFieldView]:
    """Mask a stored LLM connection's fields per the LLM registry.

    Sensitive fields return BLANK (never the ciphertext); ``source`` is
    ``encrypted`` when a value is stored so the form shows a "keep current"
    placeholder. Plain fields carry their real values.
    """
    rows: list[SecretsFieldView] = []
    for name, sensitive in provider_fields(provider):
        if sensitive:
            stored = name in encrypted
            rows.append(
                SecretsFieldView(
                    name=name,
                    value="",
                    sensitive=True,
                    source="encrypted" if stored else "default",
                )
            )
        else:
            value = plain.get(name, "")
            rows.append(
                SecretsFieldView(
                    name=name,
                    value=str(value),
                    sensitive=False,
                    source="plain" if value != "" else "default",
                )
            )
    return rows


def _build_llm_connection_view(cid: str, raw: dict[str, Any]) -> LlmConnectionView:
    """Masked view of one LLM registry connection doc."""
    provider = str(raw.get("provider") or "")
    plain = dict(raw.get("plain") or {})
    encrypted = dict(raw.get("encrypted") or {})
    configured = bool(provider) and (bool(plain) or bool(encrypted))
    return LlmConnectionView(
        id=cid,
        name=str(raw.get("name") or ""),
        provider=provider,
        model=str(raw.get("model") or ""),
        fields=_mask_llm_rows(provider, plain, encrypted),
        configured=configured,
        updated_at=str(raw.get("updated_at") or ""),
        updated_by=str(raw.get("updated_by") or ""),
    )


def _maybe_import_legacy_llm(user: str) -> None:
    """One-time migration: turn the legacy singleton ``llm`` doc into a registry
    connection + set it active.

    Runs only when the registry is empty (guarded by the caller). Unlike the DB
    import, the ``llm`` doc is KEPT — it is the runtime projection the factory
    reads. Copies the raw doc so the Fernet ciphertext is preserved.
    """
    raw = _safe_get_raw("llm")
    if not raw or not raw.get("provider"):
        return
    provider = str(raw.get("provider"))
    model = str(raw.get("model") or "")
    cid = new_llm_connection_id()
    doc = dict(raw)
    label = _PROVIDER_LABELS.get(provider, provider.replace("_", " ").title())
    doc["name"] = f"{label} · {model}" if model else label
    doc["kind"] = "llm_connection"
    _repo().upsert_raw(cid, doc)
    _repo().set_active_llm(cid, updated_by=user)
    try:
        sp = get_secrets_provider()
        sp.invalidate(LLM_ACTIVE_POINTER_ID)
        sp.invalidate(cid)
    except Exception:  # noqa: BLE001
        logger.warning("cache invalidation after legacy llm import failed", exc_info=True)
    logger.info("Imported legacy LLM config into the connection registry as %s", cid)


@router.get("/llm/connections", response_model=LlmConnectionsListResponse)
async def list_llm_connections(
    claims: TokenClaims = Depends(validate_token),
) -> LlmConnectionsListResponse:
    """List every registered LLM connection + the single active pointer.

    On first call with an empty registry, imports the legacy singleton ``llm``
    doc so the upgrade is seamless (the ``llm`` doc is kept as the projection).
    """
    user = getattr(claims, "email", None) or "anonymous"
    try:
        conns = _repo().list_llm_connections()
        if not conns:
            _maybe_import_legacy_llm(user)
            conns = _repo().list_llm_connections()
        active = _repo().get_active_llm()
    except OpenSearchException as exc:
        logger.error("OpenSearch unavailable listing llm connections: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: OpenSearch is not reachable.",
        ) from exc
    return LlmConnectionsListResponse(
        connections=[_build_llm_connection_view(cid, raw) for cid, raw in conns],
        active=LlmActiveView(active=active),
    )


@router.post("/llm/connections", response_model=LlmConnectionView)
async def create_llm_connection(
    body: LlmConnectionUpsertRequest,
    claims: TokenClaims = Depends(validate_token),
) -> LlmConnectionView:
    user = getattr(claims, "email", None) or "anonymous"
    cid = new_llm_connection_id()
    try:
        stored = _repo().upsert(
            cid,
            provider=body.provider,
            model=body.model,
            fields=body.fields,
            updated_by=user,
            extra={"name": body.name, "kind": "llm_connection"},
        )
    except OpenSearchException as exc:
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not create connection.",
        ) from exc
    _invalidate(cid)
    return _build_llm_connection_view(cid, stored)


@router.put("/llm/connections/active", response_model=LlmActiveView)
async def set_llm_active(
    body: LlmActivePutRequest,
    claims: TokenClaims = Depends(validate_token),
) -> LlmActiveView:
    """Set the single active LLM (or clear with ``null``).

    Projects the chosen connection into the canonical ``llm`` doc the runtime
    reads; ``null`` empties it (chat blocked until one is set again).
    """
    user = getattr(claims, "email", None) or "anonymous"
    if body.active and _safe_get_raw(body.active) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Connection {body.active!r} does not exist.",
        )
    try:
        _repo().set_active_llm(body.active, updated_by=user)
        _repo().project_active_llm(body.active, updated_by=user)
    except OpenSearchException as exc:
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not update active LLM.",
        ) from exc
    _invalidate(LLM_ACTIVE_POINTER_ID)
    _invalidate("llm")
    # _invalidate only evicts THIS process's read cache. The orchestrator is a
    # different container holding its own LLM-derived singletons, so it has to be
    # told as well — the legacy PUT /secrets/llm did this and the registry
    # endpoints did not, which is why activating a connection appeared to do
    # nothing until a restart. Best-effort: it degrades to a logged warning, and
    # factory.llm_revision() converges within the 60 s TTL regardless.
    _notify_orchestrator_reload(uuid.uuid4().hex)
    return LlmActiveView(active=body.active)


@router.put("/llm/connections/{cid}", response_model=LlmConnectionView)
async def update_llm_connection(
    cid: str,
    body: LlmConnectionUpsertRequest,
    claims: TokenClaims = Depends(validate_token),
) -> LlmConnectionView:
    user = getattr(claims, "email", None) or "anonymous"
    if _safe_get_raw(cid) is None:
        raise HTTPException(status_code=404, detail=f"Connection {cid!r} not found.")
    try:
        stored = _repo().upsert(
            cid,
            provider=body.provider,
            model=body.model,
            fields=body.fields,
            updated_by=user,
            preserve_blank_secrets=True,
            extra={"name": body.name, "kind": "llm_connection"},
        )
        # Re-project if this connection is the active one.
        if _repo().get_active_llm() == cid:
            _repo().project_active_llm(cid, updated_by=user)
            _invalidate("llm")
            # Editing the ACTIVE connection changes the running model/credentials
            # — same cross-container invalidation as set_llm_active.
            _notify_orchestrator_reload(uuid.uuid4().hex)
    except OpenSearchException as exc:
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not update connection.",
        ) from exc
    _invalidate(cid)
    return _build_llm_connection_view(cid, stored)


@router.delete("/llm/connections/{cid}", response_model=LlmConnectionDeleteResponse)
async def delete_llm_connection(
    cid: str,
    claims: TokenClaims = Depends(validate_token),
) -> LlmConnectionDeleteResponse:
    """Delete a connection. If it was active, the pointer + projection are cleared."""
    user = getattr(claims, "email", None) or "anonymous"
    try:
        was_active = _repo().get_active_llm() == cid
        deleted = _repo().delete(cid)
        if was_active:
            _repo().set_active_llm(None, updated_by=user)
            _repo().project_active_llm(None, updated_by=user)  # empties the projection
            _invalidate(LLM_ACTIVE_POINTER_ID)
            _invalidate("llm")
            # Deleting the active connection leaves NO LLM configured — the
            # orchestrator must drop its singletons or it keeps answering with a
            # model that is no longer registered.
            _notify_orchestrator_reload(uuid.uuid4().hex)
    except OpenSearchException as exc:
        raise HTTPException(
            status_code=503,
            detail="SECRETS_BACKEND_UNAVAILABLE: could not delete connection.",
        ) from exc
    _invalidate(cid)
    return LlmConnectionDeleteResponse(id=cid, deleted=deleted)


@router.post("/llm/connections/{cid}/test", response_model=LlmConnectionTestResponse)
async def test_llm_connection(
    cid: str,
    _claims: TokenClaims = Depends(validate_token),
) -> LlmConnectionTestResponse:
    """Probe a stored LLM connection in-process (may be non-active).

    Builds a chat model directly from the connection's decrypted fields (via
    ``factory.build_llm_probe``) — without projecting it into the live ``llm``
    doc — and runs a 1-token invocation.
    """
    raw = _safe_get_raw(cid)
    if raw is None or not raw.get("provider"):
        raise HTTPException(status_code=404, detail=f"Connection {cid!r} not found.")
    provider = str(raw.get("provider"))
    model = str(raw.get("model") or "")

    try:
        resolved = _repo().get_resolved(cid)
    except PermissionError:
        return LlmConnectionTestResponse(
            id=cid,
            success=False,
            provider=provider,
            model=model,
            latency_ms=0,
            detail="Cannot decrypt stored credentials",
            error="ENCRYPTION_KEY_MISMATCH",
        )
    fields = dict((resolved or {}).get("fields") or {})

    started = time.monotonic()
    try:
        from ask_llm_gateway.application.factory import build_llm_probe

        llm = build_llm_probe(provider, model, fields)
        llm.invoke("Reply with the single word ok")
        latency_ms = int((time.monotonic() - started) * 1000)
        return LlmConnectionTestResponse(
            id=cid,
            success=True,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            detail="LLM responded",
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        latency_ms = int((time.monotonic() - started) * 1000)
        msg = str(exc)
        if "Give Feedback / Get Help" in msg:
            msg = msg.split("Give Feedback / Get Help")[0].strip()
        if len(msg) > 500:
            msg = msg[:500] + "..."
        return LlmConnectionTestResponse(
            id=cid,
            success=False,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            detail="Test failed — see error",
            error=msg,
        )
