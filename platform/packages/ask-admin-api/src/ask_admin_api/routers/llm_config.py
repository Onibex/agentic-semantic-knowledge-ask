# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/llm/...`` — LLM + Embedder provider configuration.

Generic multi-provider router. Absorbs the former ``aicore.py`` (now at the
``/v1/admin/llm/aicore/`` sub-prefix for backward compatibility) and adds
provider-agnostic config endpoints for the ``direct`` (Anthropic/OpenAI) path.

Endpoints
─────────
POST /v1/admin/llm/aicore/config       Upload SAP AI Core service-key JSON
GET  /v1/admin/llm/aicore/config       Return AI Core file status (masked)
GET  /v1/admin/llm/aicore/deployments  Fetch running deployments from AI Core REST API
GET  /v1/admin/llm/config              Return effective LLM + Embedder config (all providers)
POST /v1/admin/llm/config              Save provider config to settings.json
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/llm", tags=["admin/llm"])

_AICORE_CONFIG_PATH = Path("config/aicore_config.json")
_SETTINGS_PATH = Path("config/settings.json")
_ENV_PATH = Path(".env")
_AICORE_REQUIRED_KEYS = ("url", "clientid", "clientsecret", "serviceurls")


# ── Pydantic models ──────────────────────────────────────────────────────────


class AicoreConfigStatus(BaseModel):
    exists: bool
    valid: bool = False
    auth_url: str = ""
    ai_api_url: str = ""
    client_id_preview: str = ""


class AicoreConfigUploadResponse(BaseModel):
    success: bool
    message: str = ""
    status: AicoreConfigStatus


class DeploymentInfo(BaseModel):
    deployment_id: str
    model_name: str


class DeploymentListResponse(BaseModel):
    deployments: list[DeploymentInfo]


class ProviderConfigField(BaseModel):
    value: str
    source: Literal["environment", "file", "default"] = "file"
    masked: bool = False


class EffectiveLLMConfig(BaseModel):
    """Active LLM + Embedder config with per-field source attribution.

    Covers both stack modes:
      managed (SAP AI Core)  → deployment IDs are the relevant fields
      direct  (LiteLLM)      → api_base / api_version / params are relevant
    """

    stack_mode: ProviderConfigField
    llm_provider: ProviderConfigField
    llm_model: ProviderConfigField
    llm_api_key: ProviderConfigField
    llm_api_base: ProviderConfigField
    llm_api_version: ProviderConfigField
    llm_deployment_id: ProviderConfigField
    embedder_provider: ProviderConfigField
    embedder_model: ProviderConfigField
    embedder_api_key: ProviderConfigField
    embedder_api_base: ProviderConfigField
    embedder_api_version: ProviderConfigField
    embedder_deployment_id: ProviderConfigField
    # params is a literal env-var map for exotic providers (Bedrock AWS_*,
    # Vertex VERTEXAI_*). Returned as-is (NOT masked) — production should
    # never push secrets through here anyway; use env vars.
    llm_params: dict[str, str] = {}
    embedder_params: dict[str, str] = {}


class ProviderConfigRequest(BaseModel):
    """Payload for POST /v1/admin/llm/config — saves to settings.json.

    Partial update: only fields present in the body are written. ``None`` means
    "do not touch"; an empty string means "explicitly clear this field".
    """

    stack_mode: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    llm_api_version: str | None = None
    llm_deployment_id: str | None = None
    llm_params: dict[str, str] | None = None
    embedder_provider: str | None = None
    embedder_model: str | None = None
    embedder_api_key: str | None = None
    embedder_api_base: str | None = None
    embedder_api_version: str | None = None
    embedder_deployment_id: str | None = None
    embedder_params: dict[str, str] | None = None


class TestProviderRequest(BaseModel):
    """Payload for POST /v1/admin/llm/test — validates credentials WITHOUT saving.

    Two target modes:
      target="llm"      → builds the chat model + sends a 5-token probe
      target="embedder" → builds the embedder + embeds a 4-char string

    The request fields mirror ProviderConfigRequest but are ALL optional: any
    field left null/empty falls back to what's currently in settings.json so a
    test of "just rotated the api_key" doesn't require re-sending everything.
    """

    target: Literal["llm", "embedder"]
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    deployment_id: str | None = None
    params: dict[str, str] | None = None


class TestProviderResponse(BaseModel):
    success: bool
    target: str
    provider: str
    model: str
    latency_ms: int
    detail: str
    error: str | None = None


# ── AI Core helpers ──────────────────────────────────────────────────────────


def _read_aicore_raw() -> dict[str, Any] | None:
    if not _AICORE_CONFIG_PATH.exists():
        return None
    try:
        return json.loads(_AICORE_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _validate_aicore(cfg: dict[str, Any]) -> tuple[bool, str]:
    missing = [k for k in _AICORE_REQUIRED_KEYS if k not in cfg]
    if missing:
        return False, f"Missing fields: {', '.join(missing)}"
    if "AI_API_URL" not in cfg.get("serviceurls", {}):
        return False, "Missing AI_API_URL in serviceurls"
    return True, "Valid"


def _aicore_status_from(cfg: dict[str, Any] | None) -> AicoreConfigStatus:
    if cfg is None:
        return AicoreConfigStatus(exists=False)
    valid, _ = _validate_aicore(cfg)
    return AicoreConfigStatus(
        exists=True,
        valid=valid,
        auth_url=cfg.get("url", ""),
        ai_api_url=cfg.get("serviceurls", {}).get("AI_API_URL", ""),
        client_id_preview=cfg.get("clientid", "")[:12],
    )


def _write_aicore_to_env(cfg: dict[str, Any]) -> None:
    """Upsert AI Core vars into .env (creates the file if missing)."""
    new_vars: dict[str, str] = {}
    if "url" in cfg:
        new_vars["AICORE_AUTH_URL"] = cfg["url"]
    if "clientid" in cfg:
        new_vars["AICORE_CLIENT_ID"] = cfg["clientid"]
    if "clientsecret" in cfg:
        new_vars["AICORE_CLIENT_SECRET"] = cfg["clientsecret"]
    if "AI_API_URL" in cfg.get("serviceurls", {}):
        new_vars["AICORE_BASE_URL"] = cfg["serviceurls"]["AI_API_URL"]
    new_vars.setdefault("AICORE_RESOURCE_GROUP", "default")

    existing: dict[str, str] = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    existing.update(new_vars)

    _ENV_PATH.write_text(
        "# SAP AI Core — auto-generated\n"
        + "\n".join(f"{k}={v}" for k, v in existing.items())
        + "\n",
        encoding="utf-8",
    )


async def _fetch_aicore_token(auth_url: str, client_id: str, client_secret: str) -> str:
    token_url = auth_url.rstrip("/") + "/oauth/token"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            token_url,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
        )
        resp.raise_for_status()
        return str(resp.json()["access_token"])


async def _fetch_aicore_deployments(ai_api_url: str, token: str) -> list[DeploymentInfo]:
    url = ai_api_url.rstrip("/") + "/v2/lm/deployments"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}", "AI-Resource-Group": "default"},
            params={"status": "RUNNING"},
        )
        resp.raise_for_status()
        data = resp.json()

    result: list[DeploymentInfo] = []
    for dep in data.get("resources", []):
        dep_id: str = dep.get("id", "")
        try:
            model_name: str = dep["details"]["resources"]["backendDetails"]["model"]["name"]
        except (KeyError, TypeError):
            model_name = dep.get("configurationName", dep_id)
        if dep_id:
            result.append(DeploymentInfo(deployment_id=dep_id, model_name=model_name))
    return result


# ── Generic config helpers ───────────────────────────────────────────────────


def _read_settings() -> dict[str, Any]:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _field(env_key: str, cfg_val: str | None, *, sensitive: bool = False) -> ProviderConfigField:
    """Build a ProviderConfigField resolving env var > settings.json."""
    env_val = os.getenv(env_key)
    if env_val:
        return ProviderConfigField(
            value="***" if sensitive else env_val,
            source="environment",
            masked=sensitive,
        )
    if cfg_val:
        return ProviderConfigField(
            value="***" if sensitive else cfg_val,
            source="file",
            masked=sensitive,
        )
    return ProviderConfigField(value="", source="default")


# ── AI Core endpoints ────────────────────────────────────────────────────────


@router.post("/aicore/config", response_model=AicoreConfigUploadResponse)
async def upload_aicore_config(
    file: UploadFile,
    claims: TokenClaims = Depends(validate_token),
) -> AicoreConfigUploadResponse:
    """Upload SAP AI Core service-key JSON; save to ``config/aicore_config.json``."""
    trace_id = uuid.uuid4().hex
    logger.info("[%s] aicore upload user=%s", trace_id, getattr(claims, "email", "?"))

    content = await file.read()
    try:
        cfg: dict[str, Any] = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    valid, msg = _validate_aicore(cfg)
    if not valid:
        raise HTTPException(status_code=422, detail=f"Invalid AI Core config: {msg}")

    _AICORE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _AICORE_CONFIG_PATH.write_bytes(content)
    logger.info("[%s] aicore_config.json saved", trace_id)

    try:
        _write_aicore_to_env(cfg)
        logger.info("[%s] .env updated", trace_id)
    except Exception as exc:
        logger.warning("[%s] .env write skipped: %s", trace_id, exc)

    return AicoreConfigUploadResponse(
        success=True,
        message="AI Core config saved.",
        status=_aicore_status_from(cfg),
    )


@router.get("/aicore/config", response_model=AicoreConfigStatus)
async def get_aicore_config_status(
    claims: TokenClaims = Depends(validate_token),
) -> AicoreConfigStatus:
    """Return whether ``aicore_config.json`` exists and is valid (no secrets exposed)."""
    return _aicore_status_from(_read_aicore_raw())


@router.get("/aicore/deployments", response_model=DeploymentListResponse)
async def list_aicore_deployments(
    claims: TokenClaims = Depends(validate_token),
) -> DeploymentListResponse:
    """Fetch RUNNING deployments from SAP AI Core via its REST API."""
    trace_id = uuid.uuid4().hex
    logger.info("[%s] aicore deployments user=%s", trace_id, getattr(claims, "email", "?"))

    cfg = _read_aicore_raw()
    if cfg is None:
        raise HTTPException(
            status_code=404,
            detail="AI Core config not found. Upload the service-key JSON first.",
        )

    valid, msg = _validate_aicore(cfg)
    if not valid:
        raise HTTPException(status_code=422, detail=f"Invalid AI Core config: {msg}")

    try:
        token = await _fetch_aicore_token(cfg["url"], cfg["clientid"], cfg["clientsecret"])
    except Exception as exc:
        logger.error("[%s] token fetch failed: %s", trace_id, exc)
        raise HTTPException(
            status_code=502, detail=f"AI Core authentication failed: {exc}"
        ) from exc

    try:
        deps = await _fetch_aicore_deployments(cfg["serviceurls"]["AI_API_URL"], token)
    except Exception as exc:
        logger.error("[%s] deployments fetch failed: %s", trace_id, exc)
        raise HTTPException(status_code=502, detail=f"Could not fetch deployments: {exc}") from exc

    logger.info("[%s] found %d deployments", trace_id, len(deps))
    return DeploymentListResponse(deployments=deps)


# ── Generic provider config endpoints ────────────────────────────────────────


@router.get("/config", response_model=EffectiveLLMConfig)
async def get_effective_llm_config(
    claims: TokenClaims = Depends(validate_token),
) -> EffectiveLLMConfig:
    """Return the effective LLM + Embedder configuration with per-field source.

    API keys are always masked (value=***) in the response regardless of source.
    """
    cfg = _read_settings()
    llm_section = cfg.get("llm") or {}
    emb_section = cfg.get("embedder") or {}

    return EffectiveLLMConfig(
        stack_mode=_field("STACK_MODE", cfg.get("stack_mode")),
        llm_provider=_field("LLM_PROVIDER", llm_section.get("provider")),
        llm_model=_field("LLM_MODEL", llm_section.get("model")),
        llm_api_key=_field("LLM_API_KEY", llm_section.get("api_key"), sensitive=True),
        llm_api_base=_field("LLM_API_BASE", llm_section.get("api_base")),
        llm_api_version=_field("LLM_API_VERSION", llm_section.get("api_version")),
        llm_deployment_id=_field(
            "LLM_DEPLOYMENT_ID",
            llm_section.get("deployment_id") or cfg.get("deployments", {}).get("llm"),
        ),
        embedder_provider=_field("EMBEDDER_PROVIDER", emb_section.get("provider")),
        embedder_model=_field("EMBEDDER_MODEL", emb_section.get("model")),
        embedder_api_key=_field("EMBEDDER_API_KEY", emb_section.get("api_key"), sensitive=True),
        embedder_api_base=_field("EMBEDDER_API_BASE", emb_section.get("api_base")),
        embedder_api_version=_field("EMBEDDER_API_VERSION", emb_section.get("api_version")),
        embedder_deployment_id=_field(
            "EMBEDDER_DEPLOYMENT_ID",
            emb_section.get("deployment_id") or cfg.get("deployments", {}).get("embeddings"),
        ),
        # params dicts: keys are env-var names (AWS_ACCESS_KEY_ID, VERTEXAI_*).
        # Values are not masked — production must inject these via env vars,
        # not via this UI. Returned for visibility / round-tripping only.
        llm_params={str(k): str(v) for k, v in (llm_section.get("params") or {}).items()},
        embedder_params={str(k): str(v) for k, v in (emb_section.get("params") or {}).items()},
    )


@router.post("/config", status_code=200)
async def save_provider_config(
    body: ProviderConfigRequest,
    claims: TokenClaims = Depends(validate_token),
) -> dict[str, str]:
    """Save LLM + Embedder provider config to settings.json.

    Only fields present in the request body are updated (partial update).
    Sensitive fields (api_key) from the request are written to settings.json;
    in production, prefer injecting secrets via env vars instead.
    """
    trace_id = uuid.uuid4().hex
    logger.info("[%s] llm config save user=%s", trace_id, getattr(claims, "email", "?"))

    cfg = _read_settings()

    if body.stack_mode is not None:
        cfg["stack_mode"] = body.stack_mode

    llm_fields = (
        body.llm_provider,
        body.llm_model,
        body.llm_api_key,
        body.llm_api_base,
        body.llm_api_version,
        body.llm_deployment_id,
        body.llm_params,
    )
    if any(v is not None for v in llm_fields):
        llm = cfg.setdefault("llm", {})
        if body.llm_provider is not None:
            llm["provider"] = body.llm_provider
        if body.llm_model is not None:
            llm["model"] = body.llm_model
        if body.llm_api_key is not None:
            llm["api_key"] = body.llm_api_key
        if body.llm_api_base is not None:
            llm["api_base"] = body.llm_api_base
        if body.llm_api_version is not None:
            llm["api_version"] = body.llm_api_version
        if body.llm_deployment_id is not None:
            llm["deployment_id"] = body.llm_deployment_id
        if body.llm_params is not None:
            # Empty dict {} explicitly clears the params map.
            llm["params"] = dict(body.llm_params)

    emb_fields = (
        body.embedder_provider,
        body.embedder_model,
        body.embedder_api_key,
        body.embedder_api_base,
        body.embedder_api_version,
        body.embedder_deployment_id,
        body.embedder_params,
    )
    if any(v is not None for v in emb_fields):
        emb = cfg.setdefault("embedder", {})
        if body.embedder_provider is not None:
            emb["provider"] = body.embedder_provider
        if body.embedder_model is not None:
            emb["model"] = body.embedder_model
        if body.embedder_api_key is not None:
            emb["api_key"] = body.embedder_api_key
        if body.embedder_api_base is not None:
            emb["api_base"] = body.embedder_api_base
        if body.embedder_api_version is not None:
            emb["api_version"] = body.embedder_api_version
        if body.embedder_deployment_id is not None:
            emb["deployment_id"] = body.embedder_deployment_id
        if body.embedder_params is not None:
            emb["params"] = dict(body.embedder_params)

    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("[%s] settings.json updated", trace_id)

    return {"status": "ok", "message": "Provider config saved to settings.json"}


# ── Test connection endpoint ─────────────────────────────────────────────────


def _merge_test_cfg(body: TestProviderRequest, current: dict[str, Any]) -> dict[str, Any]:
    """Build the dict that build_llm / build_embedder consume.

    Falls back to whatever is currently in settings.json for any field the
    test body left null, so the UI can test "I just changed the api_key" without
    re-sending the whole config.
    """
    section_key = "llm" if body.target == "llm" else "embedder"
    section = dict(current.get(section_key) or {})

    if body.provider is not None:
        section["provider"] = body.provider
    if body.model is not None:
        section["model"] = body.model
    if body.api_key is not None:
        section["api_key"] = body.api_key
    if body.api_base is not None:
        section["api_base"] = body.api_base
    if body.api_version is not None:
        section["api_version"] = body.api_version
    if body.deployment_id is not None:
        section["deployment_id"] = body.deployment_id
    if body.params is not None:
        section["params"] = dict(body.params)

    merged = {section_key: section}
    # Managed (SAP AI Core) still needs the deployment map; mirror it so the
    # factory's backward-compat path resolves correctly.
    if body.target == "llm" and body.deployment_id is not None:
        merged.setdefault("deployments", {})["llm"] = body.deployment_id
    if body.target == "embedder" and body.deployment_id is not None:
        merged.setdefault("deployments", {})["embeddings"] = body.deployment_id

    # Carry sap_ai_core.config_path so the managed path can boot AICORE_* vars.
    if "sap_ai_core" in current:
        merged["sap_ai_core"] = current["sap_ai_core"]

    return merged


@router.post("/test", response_model=TestProviderResponse)
async def test_provider_connection(
    body: TestProviderRequest,
    claims: TokenClaims = Depends(validate_token),
) -> TestProviderResponse:
    """Validate provider credentials WITHOUT saving them.

    Builds a temporary LLM or Embedder using the test payload (falling back
    to ``settings.json`` for any unset field) and sends a minimal probe:
      llm      → invoke with a 3-word prompt, capped at 8 output tokens
      embedder → embed_query of "ok"

    Reports latency + a friendly error message. Used by the SPA setup pages
    so the admin gets a green/red signal before persisting.
    """
    import time

    trace_id = uuid.uuid4().hex
    logger.info(
        "[%s] provider test target=%s user=%s", trace_id, body.target, getattr(claims, "email", "?")
    )

    current = _read_settings()
    test_cfg = _merge_test_cfg(body, current)
    section = test_cfg["llm"] if body.target == "llm" else test_cfg["embedder"]
    provider = section.get("provider", "")
    model = section.get("model", "")

    started = time.monotonic()
    try:
        from ask_llm_gateway.application.factory import build_embedder, build_llm

        if body.target == "llm":
            llm = build_llm(test_cfg)
            # Tight cap on output to keep the probe < $0.001
            result = llm.invoke("Reply with the single word ok")
            detail = f"LLM responded ({type(result).__name__})"
        else:
            embedder = build_embedder(test_cfg)
            vec = embedder.embed_query("ok")
            detail = f"Embedder returned {len(vec)}-dim vector"

        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info("[%s] test ok %dms", trace_id, latency_ms)
        return TestProviderResponse(
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
        # Strip the giant LiteLLM debug stacktrace prelude when present.
        if "Give Feedback / Get Help" in msg:
            msg = msg.split("Give Feedback / Get Help")[0].strip()
        # Cap at 500 chars so the SPA toast stays readable.
        if len(msg) > 500:
            msg = msg[:500] + "..."
        logger.warning("[%s] test failed: %s", trace_id, msg)
        return TestProviderResponse(
            success=False,
            target=body.target,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            detail="Test failed — see error",
            error=msg,
        )
