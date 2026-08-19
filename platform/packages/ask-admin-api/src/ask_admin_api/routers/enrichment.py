# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/enrich/*`` — AI-assisted enrichment for semantic-layer YAMLs.

Three endpoints. The flow the SPA implements:

  1. ``GET /v1/admin/enrich/entity/{id}/scope-defaults`` — pre-computes the
     checklist (enrichable fields, technical exclusions, smart defaults).
  2. ``POST /v1/admin/enrich/entity/preview`` — sends the WHOLE YAML to the
     LLM with the scope, returns the diff. Atomic — all-or-nothing.
  3. ``POST /v1/admin/enrich/field`` — single-field convenience. Returns the
     diff for one field; the SPA applies it via ``PATCH /v1/viz/yamls/{id}``.

Persistence is OUT of scope — the SPA accepts the diff and POSTs the
selected changes through the existing ``viz_yamls`` router.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..application.enrichment_service import EnrichmentService, compute_scope_defaults
from ..application.system_prompts_service import (
    SystemPromptsService,
    get_standards_excerpt,
)
from ..application.yaml_file_service import YAMLNotFoundError
from ..auth.validator import TokenClaims, validate_token
from ..models.enrichment import (
    EnrichEntityDraftRequest,
    EnrichEntityRequest,
    EnrichEntityResponse,
    EnrichEntityScopeDefaults,
    EnrichFieldDraftRequest,
    EnrichFieldRequest,
    EnrichFieldResponse,
    PromptPreviewRequest,
    PromptPreviewResponse,
    RelationshipSuggestDraftRequest,
    RelationshipSuggestRequest,
    RelationshipSuggestResponse,
)
from .viz_yamls import _get_yaml_service

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/admin/enrich", tags=["admin/enrich"])


# ── Service plumbing ────────────────────────────────────────────────────────


_PROMPT_SVC: SystemPromptsService | None = None
_ENRICH_SVC: EnrichmentService | None = None


class _PromptProviderAdapter:
    """Bridge ``SystemPromptsService`` to the EnrichmentService's tiny contract.

    The enrichment service only needs two operations (``get_prompt`` +
    ``get_standards_excerpt``); the adapter lets us pass the existing
    service instance without leaking the standards-loader as a separate dep.
    """

    def __init__(self, service: SystemPromptsService) -> None:
        self._service = service

    def get_prompt(self, key: str) -> str:
        return self._service.get_prompt(key)

    def get_standards_excerpt(self, layer: str | None = None) -> str:
        return get_standards_excerpt(layer)


def _prompt_service() -> SystemPromptsService:
    global _PROMPT_SVC
    if _PROMPT_SVC is None:
        _PROMPT_SVC = SystemPromptsService()
    return _PROMPT_SVC


def _enrichment_service() -> EnrichmentService:
    global _ENRICH_SVC
    if _ENRICH_SVC is None:
        _ENRICH_SVC = EnrichmentService(
            system_prompt_provider=_PromptProviderAdapter(_prompt_service()),
            organization_context_provider=_load_organization_context,
            workspace_context_provider=_load_workspace_context,
        )
    return _ENRICH_SVC


def _load_workspace_context(workspace_id: str, entity_id: str) -> str | None:
    """Build a plain-text workspace framing for the enrichment prompt.

    Resolves the workspace, lists its Business Domains, finds which BDs (if any)
    own the entity being enriched, and lists the OTHER entities in the same
    BDs (sibling entities) so the LLM can write descriptions that align with
    the surrounding domain. Fail-soft — returns None on any error.
    """
    try:
        from ..application.workspace_repository import WorkspaceRepository
        from ..application.workspace_service import WorkspaceService

        svc = WorkspaceService(WorkspaceRepository())
        ws = svc.get_workspace(workspace_id)
        bds = svc.list_business_domains(ws.id)
    except Exception:
        return None

    owning_bds = [bd for bd in bds if entity_id in (bd.data_product_ids or [])]
    if not owning_bds:
        # The admin enriched an entity that isn't in any BD of this workspace.
        # Skip the workspace block — better than misleading the model with
        # a workspace name that has no semantic link to this entity.
        return None

    sibling_ids: set[str] = set()
    for bd in owning_bds:
        for eid in bd.data_product_ids or []:
            if eid and eid != entity_id:
                sibling_ids.add(eid)

    lines: list[str] = []
    workspace_label = ws.name or ws.slug
    if ws.objective:
        lines.append(f'Workspace: "{workspace_label}" — {ws.objective}')
    else:
        lines.append(f"Workspace: {workspace_label}")

    lines.append("")
    lines.append("Business Domain(s) this entity belongs to:")
    for bd in owning_bds:
        bd_desc = (bd.description or "").strip()
        if bd_desc:
            # Keep descriptions short for the prompt; they can be long.
            short = bd_desc if len(bd_desc) < 200 else bd_desc[:200] + "…"
            lines.append(f"  - {bd.name or bd.slug}: {short}")
        else:
            lines.append(f"  - {bd.name or bd.slug}")

    if sibling_ids:
        # Cap at ~30 names — bigger workspaces don't need to flood the prompt.
        sample = sorted(sibling_ids)[:30]
        lines.append("")
        lines.append(
            f"Sibling entities in the same business domain(s) ({len(sibling_ids)} total"
            + (", showing first 30" if len(sibling_ids) > 30 else "")
            + ", names only — gives the model awareness of the surrounding "
            "domain so descriptions / synonyms align with how the entity is "
            "consumed alongside these):"
        )
        lines.append("  " + ", ".join(sample))

    return "\n".join(lines)


def reset_singletons() -> list[str]:
    """Hook for ``/v1/internal/reload`` style invalidation."""
    global _PROMPT_SVC, _ENRICH_SVC
    cleared: list[str] = []
    if _PROMPT_SVC is not None:
        _PROMPT_SVC = None
        cleared.append("enrichment.prompt_service")
    if _ENRICH_SVC is not None:
        _ENRICH_SVC = None
        cleared.append("enrichment.service")
    return cleared


def _load_organization_context() -> str | None:
    """Reuse the same render the orchestrator uses to seed the agent prompt.

    Returns ``None`` when the Organization singleton is empty / unreachable.
    Plain text — never JSON — so the LLM can read it as-is.
    """
    try:
        from ..application.workspace_repository import WorkspaceRepository
        from ..application.workspace_service import WorkspaceService

        org = WorkspaceService(WorkspaceRepository()).get_organization()
    except Exception:
        return None
    lines: list[str] = []
    if org.company_name:
        lines.append(f"Company: {org.company_name}")
    # Generic source system (system + version) — prefer the new field, fall back
    # to the deprecated SAP-specific ``sap_version`` for unmigrated orgs.
    src = (getattr(org, "source_system", "") or org.sap_version or "").strip()
    if src:
        lines.append(f"Source system: {src}")
    # ``core_bases`` (Active SAP modules) is hidden from the Organization UI
    # for now — see OrganizationPage.tsx. We also skip surfacing it in the
    # enrichment prompt so the LLM doesn't reason about a value the admin no
    # longer controls. Re-add this line if the modules editor returns.
    if not lines:
        return None
    return "\n".join(lines)


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/entity/{entity_id}/scope-defaults",
    response_model=EnrichEntityScopeDefaults,
)
async def get_entity_scope_defaults(
    entity_id: str,
    workspace_id: str | None = None,
    _claims: TokenClaims = Depends(validate_token),
) -> EnrichEntityScopeDefaults:
    """Return the Step-1 checklist (no LLM call).

    When ``workspace_id`` is supplied AND the entity belongs to at least one
    Data Product in that workspace, the response includes a plain-text
    ``workspace_context`` block — the SAME framing the preview endpoint will
    inject into the LLM prompt. Surfaced in the SPA so the admin sees the
    bias up front instead of trusting an opaque pipeline.
    """
    try:
        raw = _get_yaml_service().load_raw_by_id(entity_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    enrichable, technical, entity_level, defaults = compute_scope_defaults(raw)

    workspace_context: str | None = None
    if workspace_id:
        try:
            workspace_context = _load_workspace_context(workspace_id, entity_id)
        except Exception:  # noqa: BLE001 — boundary
            # Fail-soft: an unreachable workspace store shouldn't break the
            # scope checklist. The admin still sees the field list; only the
            # context preview is missing.
            workspace_context = None

    return EnrichEntityScopeDefaults(
        entity_id=entity_id,
        layer=str(raw.get("layer") or ""),
        enrichable_fields=enrichable,
        technical_fields=sorted(technical),
        entity_level=entity_level,
        default_selection=defaults,
        workspace_context=workspace_context,
    )


@router.post(
    "/entity/preview",
    response_model=EnrichEntityResponse,
)
async def preview_entity_enrichment(
    body: EnrichEntityRequest,
    claims: TokenClaims = Depends(validate_token),
) -> EnrichEntityResponse:
    """Step-2 of the entity flow: invoke the LLM + return the proposed diff."""
    trace_id = uuid.uuid4().hex
    logger.info(
        "[%s] enrich.entity preview entity=%s scope_fields=%d entity_level=%s user=%s",
        trace_id,
        body.entity_id,
        len(body.scope.field_names),
        body.scope.entity_level,
        getattr(claims, "email", "?"),
    )
    try:
        raw = _get_yaml_service().load_raw_by_id(body.entity_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        return _enrichment_service().preview_entity(
            entity_id=body.entity_id,
            raw_yaml=raw,
            scope=body.scope,
            workspace_id=body.workspace_id,
        )
    except ValueError as exc:
        logger.warning("[%s] enrich.entity invalid output: %s", trace_id, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("[%s] enrich.entity failed", trace_id)
        raise HTTPException(status_code=502, detail=f"Enrichment LLM error: {exc}") from exc


@router.post(
    "/entity/{entity_id}/prompt-preview",
    response_model=PromptPreviewResponse,
)
async def preview_entity_prompt(
    entity_id: str,
    body: PromptPreviewRequest,
    _claims: TokenClaims = Depends(validate_token),
) -> PromptPreviewResponse:
    """Return the (system, user) messages WITHOUT calling the LLM.

    Pure inspection: admin sees the exact text the model would see for this
    entity + scope + workspace. No tokens spent. Same builder path as
    ``POST /entity/preview`` so what you read here is what the model gets.
    """
    try:
        raw = _get_yaml_service().load_raw_by_id(entity_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    svc = _enrichment_service()
    try:
        system_msg, user_msg = svc.build_prompt_pair(
            entity_id=entity_id,
            raw_yaml=raw,
            scope=body.scope,
            workspace_id=body.workspace_id,
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("prompt-preview failed entity=%s", entity_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Provider / model so the dialog can show "Bedrock · Nova Lite — this is
    # the model that would receive this prompt".
    from ..application.enrichment_service import _peek_active_provider

    provider, model = _peek_active_provider()
    return PromptPreviewResponse(
        entity_id=entity_id,
        provider=provider,
        model=model,
        system_message=system_msg,
        user_message=user_msg,
        system_chars=len(system_msg),
        user_chars=len(user_msg),
    )


@router.post(
    "/relationships-suggest",
    response_model=RelationshipSuggestResponse,
)
async def suggest_relationship(
    body: RelationshipSuggestRequest,
    claims: TokenClaims = Depends(validate_token),
) -> RelationshipSuggestResponse:
    """Modo 2 — Complete: admin picked the target; LLM fills in the rest.

    The endpoint never writes — the SPA gets the suggestion, shows it (with
    caveats / confidence / no-match reason as applicable), and only persists
    after the admin clicks Apply. That second hop goes through the existing
    ``PATCH /v1/viz/yamls/{id}`` with ``source='ai_suggest_relationship'``
    and ``commit_notes`` carrying the caveats.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "[%s] enrich.rel_suggest source=%s target=%s user=%s",
        trace_id,
        body.source_entity_id,
        body.target_entity_id,
        getattr(claims, "email", "?"),
    )

    svc = _get_yaml_service()
    try:
        source_raw = svc.load_raw_by_id(body.source_entity_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Source entity not found: {exc}") from exc
    try:
        target_raw = svc.load_raw_by_id(body.target_entity_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Target entity not found: {exc}") from exc

    try:
        return _enrichment_service().suggest_relationship_complete(
            source_entity_id=body.source_entity_id,
            target_entity_id=body.target_entity_id,
            source_raw_yaml=source_raw,
            target_raw_yaml=target_raw,
            workspace_id=body.workspace_id,
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("[%s] enrich.rel_suggest failed", trace_id)
        raise HTTPException(
            status_code=502, detail=f"Relationship-suggest LLM error: {exc}"
        ) from exc


@router.post("/field", response_model=EnrichFieldResponse)
async def preview_field_enrichment(
    body: EnrichFieldRequest,
    claims: TokenClaims = Depends(validate_token),
) -> EnrichFieldResponse:
    """Single-field enrichment — returns description + synonyms diff."""
    trace_id = uuid.uuid4().hex
    logger.info(
        "[%s] enrich.field entity=%s field=%s user=%s",
        trace_id,
        body.entity_id,
        body.field_name,
        getattr(claims, "email", "?"),
    )
    try:
        raw = _get_yaml_service().load_raw_by_id(body.entity_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        return _enrichment_service().preview_field(
            entity_id=body.entity_id, raw_yaml=raw, field_name=body.field_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("[%s] enrich.field failed", trace_id)
        raise HTTPException(status_code=502, detail=f"Enrichment LLM error: {exc}") from exc


# ── Body-aware (draft) variants — AI on the not-yet-saved create form ─────────
# Same service methods (they already take ``raw_yaml``); these just feed the
# DRAFT body instead of loading by id. Design §3.4 / OQ#1-Q1.


@router.post("/entity/preview/draft", response_model=EnrichEntityResponse)
async def preview_entity_enrichment_draft(
    body: EnrichEntityDraftRequest,
    claims: TokenClaims = Depends(validate_token),
) -> EnrichEntityResponse:
    """Entity-level (and bulk-field) enrichment over a DRAFT node (no id)."""
    trace_id = uuid.uuid4().hex
    eid = body.entity_id or "(draft)"
    logger.info(
        "[%s] enrich.entity.draft entity=%s scope_fields=%d entity_level=%s user=%s",
        trace_id,
        eid,
        len(body.scope.field_names),
        body.scope.entity_level,
        getattr(claims, "email", "?"),
    )
    try:
        return _enrichment_service().preview_entity(
            entity_id=eid,
            raw_yaml=body.raw_yaml,
            scope=body.scope,
            workspace_id=body.workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("[%s] enrich.entity.draft failed", trace_id)
        raise HTTPException(status_code=502, detail=f"Enrichment LLM error: {exc}") from exc


@router.post("/field/draft", response_model=EnrichFieldResponse)
async def preview_field_enrichment_draft(
    body: EnrichFieldDraftRequest,
    claims: TokenClaims = Depends(validate_token),
) -> EnrichFieldResponse:
    """Single-field enrichment over a DRAFT node (no id)."""
    trace_id = uuid.uuid4().hex
    try:
        return _enrichment_service().preview_field(
            entity_id=body.entity_id or "(draft)",
            raw_yaml=body.raw_yaml,
            field_name=body.field_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("[%s] enrich.field.draft failed", trace_id)
        raise HTTPException(status_code=502, detail=f"Enrichment LLM error: {exc}") from exc


@router.post("/relationships-suggest/draft", response_model=RelationshipSuggestResponse)
async def suggest_relationship_draft(
    body: RelationshipSuggestDraftRequest,
    claims: TokenClaims = Depends(validate_token),
) -> RelationshipSuggestResponse:
    """Mode-2 Complete where the SOURCE is the in-progress draft and the TARGET
    is an existing persisted entity (loaded from the workspace by id)."""
    trace_id = uuid.uuid4().hex
    svc = _get_yaml_service()
    try:
        target_raw = svc.load_raw_by_id(body.target_entity_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Target entity not found: {exc}") from exc

    try:
        return _enrichment_service().suggest_relationship_complete(
            source_entity_id=body.source_entity_id or "(draft)",
            target_entity_id=body.target_entity_id,
            source_raw_yaml=body.source_raw_yaml,
            target_raw_yaml=target_raw,
            workspace_id=body.workspace_id,
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("[%s] enrich.rel_suggest.draft failed", trace_id)
        raise HTTPException(
            status_code=502, detail=f"Relationship-suggest LLM error: {exc}"
        ) from exc
