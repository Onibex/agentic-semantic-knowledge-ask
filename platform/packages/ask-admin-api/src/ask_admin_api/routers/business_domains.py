# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/business-domains/...`` — Singleton Business Domain routes by ID.

For ``POST`` (create) + ``GET-by-workspace`` see ``workspaces.py`` — those
endpoints are scoped under the parent workspace.

"Business Domain" was formerly "Data Product" (UX_CHANGES audit, Iter 1); the
route prefix changed from ``/v1/admin/data-products`` (hard swap, no alias).

These endpoints keep the DataProduct lifecycle reverse index
(``business_domain_ids``) in sync: any membership change recomputes the reverse
index for the affected DPs (best-effort — never fails the request).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..application.env_targets import ALL_ENVIRONMENTS
from ..application.lifecycle_service import LifecycleService, PublishNotReadyError
from ..application.publish_service import PublishService
from ..application.workspace_service import (
    BusinessDomainNotFoundError,
    SlugConflictError,
    WorkspaceService,
)
from ..application.yaml_file_service import YAMLNotFoundError
from ..auth.validator import TokenClaims, validate_token
from ..config import get_settings
from ..models.data_products import DataProductLifecycle
from ..models.workspaces import BusinessDomain, BusinessDomainUpdate, DataProductRef
from ..models.yaml_ingestion import (
    DomainPublishItem,
    DomainPublishRequest,
    DomainPublishResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/business-domains", tags=["admin/business-domains"])

_svc: WorkspaceService | None = None
_lifecycle: LifecycleService | None = None


def _service() -> WorkspaceService:
    global _svc
    if _svc is None:
        _svc = WorkspaceService()
    return _svc


def _lifecycle_service() -> LifecycleService:
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = LifecycleService()
    return _lifecycle


def _author_email(claims: TokenClaims) -> str:
    return getattr(claims, "email", None) or getattr(claims, "sub", "unknown") or "unknown"


def sync_membership(affected_entity_ids: set[str]) -> None:
    """Recompute the DP reverse index for ``affected_entity_ids``. Best-effort.

    Shared by the create endpoint in ``workspaces.py`` and the update/delete
    endpoints here. Never raises — a stale reverse index is fixed by the
    ``/v1/admin/lifecycle/rebuild`` endpoint.
    """
    if not affected_entity_ids:
        return
    try:
        all_bds = _service().list_all_business_domains()
        _lifecycle_service().recompute_membership(affected_entity_ids, all_bds)
    except Exception:  # noqa: BLE001 — denormalization upkeep, never blocks the write
        logger.warning("Reverse-index sync failed for %s", affected_entity_ids, exc_info=True)


@router.get("/{bd_id}", response_model=BusinessDomain)
async def get_business_domain(
    bd_id: str,
    _claims: TokenClaims = Depends(validate_token),
) -> BusinessDomain:
    try:
        return _service().get_business_domain(bd_id)
    except BusinessDomainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Business domain not found: {bd_id}") from exc


@router.patch("/{bd_id}", response_model=BusinessDomain)
async def update_business_domain(
    bd_id: str,
    body: BusinessDomainUpdate,
    claims: TokenClaims = Depends(validate_token),
) -> BusinessDomain:
    try:
        before = _service().get_business_domain(bd_id)
        updated = _service().update_business_domain(bd_id, body, author_email=_author_email(claims))
    except BusinessDomainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Business domain not found: {bd_id}") from exc
    except SlugConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Resync the reverse index ONLY for entities whose membership in THIS BD
    # actually changed — the symmetric difference (entered XOR left), not the
    # union. An entity that stayed a member keeps the same business_domain_ids,
    # so re-upserting it is a wasted ``refresh="wait_for"`` write (~1s each) — a
    # plain add/remove of one DP must not pay N seconds to rewrite every member.
    affected = set(before.data_product_ids) ^ set(updated.data_product_ids)
    sync_membership(affected)
    return updated


@router.post("/{bd_id}/data-products", response_model=BusinessDomain)
async def add_data_product(
    bd_id: str,
    body: DataProductRef,
    background: BackgroundTasks,
    claims: TokenClaims = Depends(validate_token),
) -> BusinessDomain:
    """Atomically add ONE Data Product to a Business Domain (add-if-absent).

    Incremental counterpart of the full-array PATCH — the SPA's "+"/drag uses
    this so a burst of rapid adds can't lose updates (the server applies an
    atomic scripted update; concurrent adds are commutative). The reverse-index
    sync runs in the background — it's best-effort denormalization and must not
    add ~1s of ``refresh="wait_for"`` latency to an interactive click.
    """
    try:
        updated = _service().add_data_product(
            bd_id, body.entity_id, author_email=_author_email(claims)
        )
    except BusinessDomainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Business domain not found: {bd_id}") from exc
    background.add_task(sync_membership, {body.entity_id})
    return updated


@router.delete("/{bd_id}/data-products/{entity_id}", response_model=BusinessDomain)
async def remove_data_product(
    bd_id: str,
    entity_id: str,
    background: BackgroundTasks,
    claims: TokenClaims = Depends(validate_token),
) -> BusinessDomain:
    """Atomically remove ONE Data Product from a Business Domain (membership only).

    Idempotent — removing a non-member is a no-op. Like the add endpoint, the
    reverse-index sync is deferred to a background task.
    """
    try:
        updated = _service().remove_data_product(
            bd_id, entity_id, author_email=_author_email(claims)
        )
    except BusinessDomainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Business domain not found: {bd_id}") from exc
    background.add_task(sync_membership, {entity_id})
    return updated


@router.delete("/{bd_id}", status_code=200)
async def delete_business_domain(
    bd_id: str,
    _claims: TokenClaims = Depends(validate_token),
) -> dict[str, bool]:
    affected: set[str] = set()
    try:
        existing = _service().get_business_domain(bd_id)
        affected = set(existing.data_product_ids)
    except BusinessDomainNotFoundError:
        pass
    deleted = _service().delete_business_domain(bd_id)
    if deleted:
        sync_membership(affected)
    return {"deleted": deleted}


# ── Domain-level bulk publish (Iter 5 / CH-5) ───────────────────────────────


def _needs_publish(lc: DataProductLifecycle | None, env: str) -> tuple[bool, str | None]:
    """Whether a DP has changes pending for ``env`` (mirrors the DeploymentPanel
    gate). Returns ``(needs, skip_reason)``."""
    if env == "dev":
        if lc is None or lc.dev_published is None or lc.dev_published.sha != lc.main_sha:
            return True, None
        return False, "already up to date with working"
    # prod
    if lc is None or lc.dev_published is None:
        return False, "needs a dev publish first"
    if lc.prod_published is not None and lc.prod_published.sha == lc.dev_published.sha:
        return False, "already up to date with dev"
    return True, None


@router.post("/{bd_id}/publish/{env}", response_model=DomainPublishResult)
async def publish_business_domain(
    bd_id: str,
    env: str,
    claims: TokenClaims = Depends(validate_token),
) -> DomainPublishResult:
    """Publish every Data Product in a Business Domain to ``env`` (UX_CHANGES §6.5).

    Iterates ``data_product_ids``, publishing the ones with changes pending and
    skipping those already up to date / not ready (prod needs a dev publish
    first). The per-DP gate from CH-4 still applies. Returns per-DP outcomes for
    the SPA result modal.
    """
    if env not in ALL_ENVIRONMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown environment '{env}' — expected one of {list(ALL_ENVIRONMENTS)}.",
        )
    try:
        bd = _service().get_business_domain(bd_id)
    except BusinessDomainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Business domain not found: {bd_id}") from exc

    settings = get_settings()
    publisher = PublishService(repo_root=settings.repo_root, workspace_path=settings.workspace_path)
    lifecycle = _lifecycle_service()
    by = _author_email(claims)

    items: list[DomainPublishItem] = []
    for dp_id in bd.data_product_ids:
        needs, skip_reason = _needs_publish(lifecycle.get(dp_id), env)
        if not needs:
            items.append(DomainPublishItem(entity_id=dp_id, outcome="skipped", reason=skip_reason))
            continue
        try:
            outcome = publisher.publish(dp_id, env, by=by)
            items.append(
                DomainPublishItem(
                    entity_id=dp_id, outcome="published", committed_sha=outcome.committed_sha
                )
            )
        except PublishNotReadyError as exc:
            items.append(DomainPublishItem(entity_id=dp_id, outcome="skipped", reason=str(exc)))
        except YAMLNotFoundError:
            items.append(
                DomainPublishItem(
                    entity_id=dp_id, outcome="error", reason="YAML not found in workspace"
                )
            )
        except Exception as exc:  # noqa: BLE001 — one DP's failure must not abort the batch
            logger.exception("domain publish: %s → %s failed", dp_id, env)
            items.append(DomainPublishItem(entity_id=dp_id, outcome="error", reason=str(exc)))

    return DomainPublishResult(
        business_domain_id=bd.id,
        env=env,
        total=len(items),
        published=sum(1 for i in items if i.outcome == "published"),
        skipped=sum(1 for i in items if i.outcome == "skipped"),
        failed=sum(1 for i in items if i.outcome == "error"),
        items=items,
    )


@router.post("/{bd_id}/publish/{env}/stream")
async def publish_business_domain_stream(
    bd_id: str,
    env: str,
    body: DomainPublishRequest | None = None,
    claims: TokenClaims = Depends(validate_token),
) -> StreamingResponse:
    """Streaming (NDJSON) variant of the domain bulk publish.

    Same work as :func:`publish_business_domain`, but emits one JSON object per
    line as each Data Product is processed so the SPA can show live per-DP
    progress — which DP is publishing *now*, which already finished — instead of
    one blocking response. A long batch no longer looks like a hung console.

    Event stream (one JSON per line, ``application/x-ndjson``)::

        {"type": "start",      "total": N, "planned": [id, ...]}
        {"type": "processing", "entity_id": id, "index": i}      # before each DP
        {"type": "item",       "entity_id": id, "index": i, "outcome": ...}
        {"type": "done",       "published": p, "skipped": s, "failed": f}

    ``body.entity_ids`` (optional) restricts the publish to a chosen subset (the
    SPA checklist); ids that aren't members of the domain are ignored. The
    per-DP gate from ``_needs_publish`` still applies.
    """
    if env not in ALL_ENVIRONMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown environment '{env}' — expected one of {list(ALL_ENVIRONMENTS)}.",
        )
    try:
        bd = _service().get_business_domain(bd_id)
    except BusinessDomainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Business domain not found: {bd_id}") from exc

    settings = get_settings()
    publisher = PublishService(repo_root=settings.repo_root, workspace_path=settings.workspace_path)
    lifecycle = _lifecycle_service()
    by = _author_email(claims)

    # Resolve the ordered target list: the domain's members, optionally narrowed
    # to the requested subset (intersection preserves the domain's order and
    # silently drops ids that are not members).
    requested = set(body.entity_ids) if body and body.entity_ids is not None else None
    targets = [dp_id for dp_id in bd.data_product_ids if requested is None or dp_id in requested]

    async def _events() -> AsyncIterator[bytes]:
        def emit(obj: dict) -> bytes:
            return (json.dumps(obj) + "\n").encode("utf-8")

        yield emit(
            {
                "type": "start",
                "env": env,
                "business_domain_id": bd.id,
                "total": len(targets),
                "planned": targets,
            }
        )
        published = skipped = failed = 0
        for index, dp_id in enumerate(targets):
            yield emit({"type": "processing", "entity_id": dp_id, "index": index})
            outcome_name: str
            committed_sha: str | None = None
            reason: str | None = None
            try:
                # Gate + publish run in a worker thread so the event loop can
                # flush each line between DPs (publish does blocking git + OS I/O).
                lc = await asyncio.to_thread(lifecycle.get, dp_id)
                needs, skip_reason = _needs_publish(lc, env)
                if not needs:
                    outcome_name, reason, skipped = "skipped", skip_reason, skipped + 1
                else:
                    result = await asyncio.to_thread(publisher.publish, dp_id, env, by=by)
                    outcome_name, committed_sha, published = (
                        "published",
                        result.committed_sha,
                        published + 1,
                    )
            except PublishNotReadyError as exc:
                outcome_name, reason, skipped = "skipped", str(exc), skipped + 1
            except YAMLNotFoundError:
                outcome_name, reason, failed = "error", "YAML not found in workspace", failed + 1
            except Exception as exc:  # noqa: BLE001 — one DP's failure must not abort the batch
                logger.exception("domain publish (stream): %s → %s failed", dp_id, env)
                outcome_name, reason, failed = "error", str(exc), failed + 1
            yield emit(
                {
                    "type": "item",
                    "index": index,
                    "entity_id": dp_id,
                    "outcome": outcome_name,
                    "committed_sha": committed_sha,
                    "reason": reason,
                }
            )
        yield emit(
            {
                "type": "done",
                "env": env,
                "business_domain_id": bd.id,
                "total": len(targets),
                "published": published,
                "skipped": skipped,
                "failed": failed,
            }
        )

    return StreamingResponse(
        _events(),
        media_type="application/x-ndjson",
        # Defeat proxy buffering (nginx) so each line reaches the SPA immediately.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
