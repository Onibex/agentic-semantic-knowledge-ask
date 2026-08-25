# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unified multi-provider factory for LLM and Embedder instances.

All consumers MUST use build_llm() / build_embedder() — never import a
specific adapter from infrastructure/.

Resolution priority (highest wins):

    1. Encrypted secrets backend (``ask-system-settings-v1`` in OpenSearch
       via SecretsProvider). Canonical store post-Iter encrypted-secrets.
       Exports fields to os.environ before resolving anything else.
    2. Environment variables (LLM_*, EMBEDDER_*, AWS_*, AICORE_*…). These
       are set by step 1 OR by the deployment manifest / .env directly.
    3. ``config/settings.json`` ``llm`` / ``embedder`` sections. Legacy
       dev-time fallback; will be empty once the migration script runs.
    4. ``deployments`` legacy shape — assume ``sap_aicore`` provider.

Two paths only:
  * ``sap_aicore``  → native gen_ai_hub adapter (SAP AI Core; LiteLLM cannot
                      proxy its deployment-id routing).
  * everything else → LiteLLM (Bedrock, Azure, OpenAI, Anthropic, Vertex/Gemini,
                      Mistral, Cohere, … — adding one is config, not code).
  * embedder ``huggingface`` → local sentence-transformers (offline, no API).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _env_or(env_key: str, cfg_val: str | None, default: str = "") -> str:
    """Return env var if set, else cfg value, else default."""
    return os.getenv(env_key) or cfg_val or default


def _seed_env_from_secrets(target: str) -> None:
    """Best-effort: load encrypted-secrets backend doc into ``os.environ``.

    Silently skips on backend failures (OpenSearch unreachable, no doc stored
    yet) so dev environments without the new infra keep working. Crypto
    failures (missing / invalid master key when there ARE encrypted fields to
    decrypt) propagate — that is fail-closed by design.
    """
    try:
        from ..infrastructure.secrets import get_secrets_provider

        get_secrets_provider().export_to_env(target)
    except PermissionError:
        # ENCRYPTION_KEY_MISMATCH — stored cipher does not decrypt with the
        # current master key. Surface clearly; this is a deployment problem.
        raise
    except Exception as exc:  # noqa: BLE001 — boundary
        # OpenSearch down, no doc stored, etc. Let the factory fall through
        # to settings.json / env vars so dev environments still boot.
        logger.debug("SecretsProvider skipped for %s: %s", target, exc)


# ── LLM ─────────────────────────────────────────────────────────────────────


def _resolve_llm_provider(cfg: dict[str, Any]) -> str:
    llm_section = cfg.get("llm") or {}
    provider = _env_or("LLM_PROVIDER", llm_section.get("provider"))
    # `or {}` (not `.get(_, {})`) — the key may exist with an explicit None
    # value, e.g. the enrichment service builds {"deployments": cfg.get(...)}.
    deployments = cfg.get("deployments") or {}
    if not provider and deployments.get("llm"):
        provider = "sap_aicore"  # backward-compat: old settings shape
    return provider


def build_llm(config: dict[str, Any]) -> Any:
    """Return a LangChain chat model for the active provider.

    Raises ValueError when no provider is configured.
    """
    _seed_env_from_secrets("llm")

    llm_section = _llm_section_from_secrets() or config.get("llm") or {}
    provider = _resolve_llm_provider({"llm": llm_section, "deployments": config.get("deployments")})

    if not provider:
        raise ValueError(
            "No LLM provider configured. Set LLM_PROVIDER env var, "
            "store a config via /v1/admin/secrets/llm, or set config['llm']['provider']."
        )

    if provider == "sap_aicore":
        from .chat_llm_factory import get_chat_llm

        # SAP AI Core still reads aicore_config.json via the settings dict.
        return get_chat_llm(config)

    # Every other provider goes through LiteLLM.
    from ..infrastructure.litellm_llm import build_litellm_chat

    return build_litellm_chat(
        provider=provider,
        model=_env_or("LLM_MODEL", llm_section.get("model")),
        api_key=_env_or("LLM_API_KEY", llm_section.get("api_key")) or None,
        api_base=_env_or("LLM_API_BASE", llm_section.get("api_base")) or None,
        api_version=_env_or("LLM_API_VERSION", llm_section.get("api_version")) or None,
        params=llm_section.get("params") or None,
        max_tokens=_resolve_max_tokens(llm_section),
    )


def _resolve_max_tokens(llm_section: dict[str, Any]) -> int:
    """Output-token ceiling for SQL generation et al.

    Configurable so complex multi-CTE SQL is not truncated mid-string (which
    surfaced as 'Failed to parse LLM JSON response: Unterminated string').
    Precedence: LLM_MAX_TOKENS env > llm.params.max_tokens > 8192 default.
    It is a CEILING, not a target — raising it does not cost more for short
    answers; you only pay for tokens actually generated.
    """
    params = llm_section.get("params") or {}
    raw = os.getenv("LLM_MAX_TOKENS") or params.get("max_tokens") or 8192
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 8192


def _llm_section_from_secrets() -> dict[str, Any] | None:
    """Build the in-memory ``llm`` section from the secrets backend.

    Returns None when no doc is stored (dev fallback to settings.json).
    Fields are read from the resolved doc rather than env vars so we have
    a single source of truth for provider/model selection (env vars carry
    the credentials, the doc carries the routing).

    ``updated_at`` is carried through for :func:`llm_revision` — it is the only
    signal that catches a credential rotation that leaves provider+model
    unchanged. Ignored by ``build_llm``.
    """
    try:
        from ..infrastructure.secrets import get_secrets_provider

        resolved = get_secrets_provider().get("llm")
    except Exception:  # noqa: BLE001 — see _seed_env_from_secrets
        return None
    if not resolved:
        return None
    return {
        "provider": resolved.get("provider", ""),
        "model": resolved.get("model", ""),
        "updated_at": resolved.get("updated_at", ""),
    }


# ── Config revision (cache key for consumers) ────────────────────────────────


def _target_revision(target: str, section: dict[str, Any] | None) -> str:
    """``provider|model|updated_at`` for one secrets target, plus the env
    overrides that outrank it. Empty string when nothing is stored."""
    if not section:
        return ""
    prefix = "LLM_" if target == "llm" else "EMBEDDER_"
    provider = _env_or(f"{prefix}PROVIDER", section.get("provider"))
    model = _env_or(f"{prefix}MODEL", section.get("model"))
    return "|".join(
        (
            provider,
            model,
            str(section.get("updated_at") or ""),
            os.getenv(f"{prefix}MAX_TOKENS", ""),
        )
    )


def llm_revision() -> str:
    """Fingerprint of the ACTIVE LLM configuration. Safe on the hot path.

    Any consumer that caches an object built from :func:`build_llm` — a
    ``prompt | llm | parser`` chain, a SQL generator, a strategy bundle — MUST
    key that cache on this value. ``ChatLiteLLM`` bakes ``model=`` into its
    constructor, so a cached instance is pinned to the model that was active
    when it was built; without a revision key it survives until the process
    restarts and an admin switching the active LLM in ASK Setup sees no effect.

    Cheap: reads the SAME TTL-cached ``SecretsProvider`` doc that ``build_llm``
    reads, so inside the cache window (60 s) this is a dict lookup with no I/O.
    Staleness is bounded by that TTL instead of by the process lifetime.

    Pull, not push, deliberately. A POST-to-invalidate reaches exactly one pod
    and only fires from the write paths that remember to call it; a fingerprint
    converges no matter who wrote the change — registry endpoint, the legacy
    ``PUT /v1/admin/secrets/llm``, a direct OpenSearch edit — and it stays
    correct with more than one replica.

    Returns ``""`` when no secrets doc is stored, i.e. the legacy
    ``settings.json`` fallback. That plane is not fingerprinted: it is edited on
    disk and keeps using the explicit ``POST /v1/internal/reload`` hook.
    """
    return _target_revision("llm", _llm_section_from_secrets())


def embedder_revision() -> str:
    """:func:`llm_revision` for the embedder target — see it for the rationale.

    Consumed by caches that hold a ``build_embedder`` result (the Precise
    strategy bundle). Note that changing the embedder invalidates every stored
    vector too, so a rebuild here is necessary but not sufficient; the SPA warns
    about the required re-ingest separately.
    """
    return _target_revision("embedder", _embedder_section_from_secrets())


def build_llm_probe(provider: str, model: str, fields: dict[str, str]) -> Any:
    """Build a chat model DIRECTLY from explicit ``(provider, model, fields)``.

    Unlike :func:`build_llm`, this does NOT read the secrets store — it lets the
    LLM-connection ``/test`` endpoint probe a *specific* registered connection
    (which may not be the active one) without projecting it into the live ``llm``
    doc. ``fields`` are the resolved (decrypted) connection fields.

    Credentials are seeded into ``os.environ`` (LLM_ prefix for
    api_key/api_base/api_version/deployment_id; AWS_*/VERTEXAI_*/GOOGLE_* verbatim)
    so env-var providers (Bedrock, Vertex) work. Both writes are ledgered: the
    field seeding shares the ``llm`` plane, so the next real ``build_llm()``
    replaces it, and the LiteLLM layer writes under its own ``probe`` scope so
    testing one connection never retires the credentials of the active one.
    """
    if not provider:
        raise ValueError("No provider configured for the connection under test.")

    from ..infrastructure.secrets import export_fields_to_env

    export_fields_to_env("llm", fields)

    if provider == "sap_aicore":
        from .chat_llm_factory import get_chat_llm

        return get_chat_llm({"deployments": {"llm": fields.get("deployment_id", "")}})

    from ..infrastructure.litellm_llm import build_litellm_chat

    return build_litellm_chat(
        provider=provider,
        scope="probe",
        model=model,
        api_key=fields.get("api_key") or None,
        api_base=fields.get("api_base") or None,
        api_version=fields.get("api_version") or None,
        params=None,
        max_tokens=256,
    )


# ── Embedder ─────────────────────────────────────────────────────────────────


def _resolve_embedder_provider(cfg: dict[str, Any]) -> str:
    emb_section = cfg.get("embedder") or {}
    provider = _env_or("EMBEDDER_PROVIDER", emb_section.get("provider"))
    # `or {}` (not `.get(_, {})`) — see _resolve_llm_provider for the rationale.
    deployments = cfg.get("deployments") or {}
    if not provider and deployments.get("embeddings"):
        provider = "sap_aicore"  # backward-compat: old settings shape
    return provider


def build_embedder(config: dict[str, Any]) -> Any:
    """Return an embedder for the active provider.

    Raises ValueError when no provider is configured.
    """
    _seed_env_from_secrets("embedder")

    emb_section = _embedder_section_from_secrets() or config.get("embedder") or {}
    provider = _resolve_embedder_provider(
        {"embedder": emb_section, "deployments": config.get("deployments")}
    )

    if not provider:
        raise ValueError(
            "No embedder provider configured. "
            "Set EMBEDDER_PROVIDER env var, store a config via "
            "/v1/admin/secrets/embedder, or set config['embedder']['provider']."
        )

    if provider == "sap_aicore":
        from .embedder_factory import get_embedder

        return get_embedder(config)

    if provider == "huggingface":
        # Local sentence-transformers — runs offline, not a LiteLLM provider.
        from ..infrastructure.huggingface_embedder import HuggingFaceEmbedder

        return HuggingFaceEmbedder(
            model=_env_or("EMBEDDER_MODEL", emb_section.get("model")),
            api_key=_env_or("EMBEDDER_API_KEY", emb_section.get("api_key")),
        )

    # Every other provider goes through LiteLLM.
    from ..infrastructure.litellm_embedder import LiteLLMEmbedder

    return LiteLLMEmbedder(
        provider=provider,
        model=_env_or("EMBEDDER_MODEL", emb_section.get("model")),
        api_key=_env_or("EMBEDDER_API_KEY", emb_section.get("api_key")) or None,
        api_base=_env_or("EMBEDDER_API_BASE", emb_section.get("api_base")) or None,
        api_version=_env_or("EMBEDDER_API_VERSION", emb_section.get("api_version")) or None,
        params=emb_section.get("params") or None,
    )


def _embedder_section_from_secrets() -> dict[str, Any] | None:
    """Same pattern as ``_llm_section_from_secrets``, for the embedder target."""
    try:
        from ..infrastructure.secrets import get_secrets_provider

        resolved = get_secrets_provider().get("embedder")
    except Exception:  # noqa: BLE001
        return None
    if not resolved:
        return None
    return {
        "provider": resolved.get("provider", ""),
        "model": resolved.get("model", ""),
        "updated_at": resolved.get("updated_at", ""),
    }


# ── Display label ────────────────────────────────────────────────────────────


def get_provider_display(config: dict[str, Any]) -> str:
    """Return a human-readable label for the active LLM configuration."""
    # Prefer the secrets backend so the chip label reflects what runtime uses.
    section = _llm_section_from_secrets() or config.get("llm") or {}
    provider = _env_or("LLM_PROVIDER", section.get("provider"))
    deployments = config.get("deployments") or {}
    if not provider and deployments.get("llm"):
        provider = "sap_aicore"
    model = _env_or("LLM_MODEL", section.get("model")) or config.get("model_name", "")

    if not provider:
        return "Unknown"
    if provider == "sap_aicore":
        deployment_id = deployments.get("llm", "") or ""
        label = model or deployment_id[:25]
        return f"SAP AI Core · {label}"
    # LiteLLM providers — show provider + model as-is.
    pretty = provider.replace("_", " ").title()
    return f"{pretty} · {model}" if model else pretty
