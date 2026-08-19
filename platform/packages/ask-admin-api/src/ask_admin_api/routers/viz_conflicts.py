# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""/v1/viz/yamls/{yaml_id}/conflicts — Conflict listing and resolution.

Iter 5: Exposes the conflict blocks produced by the SAP JSON merge engine
and provides a resolution endpoint (keep_enriched | accept_sap).
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ask_knowledge_graph.infrastructure.yaml_serializer import (
    AskYamlSerializer,
    load_yaml_text,
)

from ..application.conflict_store import ConflictStore
from ..application.enrichments_store import EnrichmentsStore
from ..application.git_service import GitService
from ..application.merge_engine import _remove_field
from ..application.sap_merge_service import (
    _rederive_grain_and_fanout,
    _resync_bronze_primary_key,
)
from ..application.yaml_file_service import YAMLFileService, YAMLNotFoundError
from ..auth.validator import TokenClaims, validate_token
from ..config import get_settings
from ..models.viz_models import (
    BulkConflictResolutionRequest,
    ConflictBlock,
    ConflictResolutionRequest,
    VizYAMLNode,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/viz", tags=["viz"])

# ── Lazy singletons ──────────────────────────────────────────────────────────

_yaml_svc_lock = threading.Lock()
_yaml_svc: YAMLFileService | None = None
_git_svc_lock = threading.Lock()
_git_svc: GitService | None = None


def _get_yaml_service() -> YAMLFileService:
    global _yaml_svc
    if _yaml_svc is not None:
        return _yaml_svc
    with _yaml_svc_lock:
        if _yaml_svc is not None:
            return _yaml_svc
        s = get_settings()
        _yaml_svc = YAMLFileService(workspace_path=s.workspace_path, repo_root=s.repo_root)
    return _yaml_svc


def _get_git_service() -> GitService:
    global _git_svc
    if _git_svc is not None:
        return _git_svc
    with _git_svc_lock:
        if _git_svc is not None:
            return _git_svc
        s = get_settings()
        _git_svc = GitService(repo_root=s.repo_root)
    return _git_svc


# ── Helpers ──────────────────────────────────────────────────────────────────


def _apply_sap_value_to_field(raw: dict, field_name: str, sap_value: dict, is_bronze: bool) -> None:
    """Overlay SAP's value onto the existing YAML field.

    ``sap_value`` only carries the properties SAP knows about — typically
    ``{type, source, description}`` for Silvers and ``{type, description}``
    for Bronces. NEVER ``name``, NEVER ``field_role`` / ``alias`` /
    ``synonyms``. A naïve replace destroys those required + admin-curated
    properties and leaves a corrupted entry that the next ingest / publish
    cannot validate against SilverNode / BronzeNode.

    We MERGE instead: start from the existing field dict (preserving name +
    role + alias + everything the admin curated outside the conflicted
    property), then overlay sap_value on top. The name is force-set at
    the end as a safety belt.
    """
    sap_payload = sap_value if isinstance(sap_value, dict) else {}

    if is_bronze:
        fields = raw.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        existing = fields.get(field_name) if isinstance(fields.get(field_name), dict) else {}
        merged = dict(existing)
        merged.update(sap_payload)
        fields[field_name] = merged
        raw["fields"] = fields
    else:
        fields_list = raw.get("fields") or []
        by_name = {
            f["name"]: i for i, f in enumerate(fields_list) if isinstance(f, dict) and "name" in f
        }
        if field_name in by_name:
            idx = by_name[field_name]
            existing = fields_list[idx] if isinstance(fields_list[idx], dict) else {}
            merged = dict(existing)
            merged.update(sap_payload)
            merged["name"] = field_name  # safety belt: never lose the name
            fields_list[idx] = merged
        else:
            new_field = dict(sap_payload)
            new_field["name"] = field_name
            fields_list.append(new_field)
        raw["fields"] = fields_list


# ── Endpoints ────────────────────────────────────────────────────────────────


def _get_conflict_store() -> ConflictStore:
    settings = get_settings()
    return ConflictStore(Path(settings.repo_root).resolve() / settings.baseline_path)


def _get_enrichments_store() -> EnrichmentsStore:
    settings = get_settings()
    return EnrichmentsStore(Path(settings.repo_root).resolve() / settings.baseline_path)


def _drop_field_props(
    field_enr: dict[str, list[str]], field_name: str, props: list[str]
) -> dict[str, list[str]]:
    """Relinquish ``props`` for ``field_name`` (admin accepted SAP for them).

    Removes only the named properties — siblings the admin still owns survive,
    mirroring the entity-level path. Drops the field key entirely when nothing
    enriched remains. An empty ``props`` (defensive) relinquishes the whole
    field, matching the prior accept-SAP behaviour."""
    result = dict(field_enr)
    if not props:
        result.pop(field_name, None)
        return result
    remaining = [p for p in result.get(field_name, []) if p not in props]
    if remaining:
        result[field_name] = remaining
    else:
        result.pop(field_name, None)
    return result


def _scrub_legacy_meta(
    raw: dict, field_name: str, enriched_props: list[str], is_entity_level: bool
) -> None:
    """Remove relinquished provenance from any LEGACY inline ``_meta`` block.

    The ``.enrichments.json`` sidecar is the source of truth, but
    ``_extract_meta`` falls back to ``_meta`` when the sidecar is empty. After
    accept-SAP empties the sidecar, a stale ``_meta`` would otherwise resurrect
    the conflict on the next ingest. Keep the YAML body clean: drop emptied
    keys and the block itself when bare."""
    meta_raw = raw.get("_meta")
    if not isinstance(meta_raw, dict):
        return
    if is_entity_level:
        ent = [p for p in (meta_raw.get("entity_enrichments") or []) if p not in enriched_props]
        if ent:
            meta_raw["entity_enrichments"] = ent
        else:
            meta_raw.pop("entity_enrichments", None)
    else:
        fields = _drop_field_props(
            dict(meta_raw.get("field_enrichments") or {}), field_name, enriched_props
        )
        if fields:
            meta_raw["field_enrichments"] = fields
        else:
            meta_raw.pop("field_enrichments", None)
    if meta_raw:
        raw["_meta"] = meta_raw
    else:
        raw.pop("_meta", None)


@router.get("/conflicts/pending", response_model=list[ConflictBlock])
async def list_pending_conflicts_workspace(
    _user: TokenClaims = Depends(validate_token),
) -> list[ConflictBlock]:
    """List every UNresolved conflict across the workspace.

    Pass H: the source of truth is now ``.sap_baseline/<id>.conflicts.json``
    sidecar files. The store walks them once and unions the unresolved
    blocks — O(files) instead of O(YAMLs) and far cheaper than the
    previous get_yaml-per-id walk.
    """
    store = _get_conflict_store()
    raw = store.list_all_pending()
    result: list[ConflictBlock] = []
    for c in raw:
        try:
            result.append(ConflictBlock(**c))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping malformed conflict block: %s", exc)
    return result


@router.get("/yamls/{yaml_id}/conflicts", response_model=list[ConflictBlock])
async def list_conflicts(
    yaml_id: str,
    include_resolved: Annotated[
        bool, Query(description="Include already-resolved conflicts")
    ] = False,
    _user: TokenClaims = Depends(validate_token),
) -> list[ConflictBlock]:
    """List conflict blocks for a single YAML node."""
    store = _get_conflict_store()
    raw = store.list_for(yaml_id, include_resolved=include_resolved)
    result: list[ConflictBlock] = []
    for c in raw:
        try:
            result.append(ConflictBlock(**c))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping malformed conflict block in %s: %s", yaml_id, exc)
    return result


@router.post("/yamls/{yaml_id}/conflicts/{conflict_id}/resolve", response_model=VizYAMLNode)
async def resolve_conflict(
    yaml_id: str,
    conflict_id: str,
    req: ConflictResolutionRequest,
    _user: TokenClaims = Depends(validate_token),
) -> VizYAMLNode:
    """Resolve a single conflict block.

    decision=keep_enriched: Mark conflict resolved, do NOT change the field value
      (keeps enriched properties intact). Removes from field_enrichments record
      since resolution is now explicit.
    decision=accept_sap: Apply the SAP value to the YAML field and remove the
      field from field_enrichments (SAP is now authoritative for this field).
    """
    if req.decision not in ("keep_enriched", "accept_sap"):
        raise HTTPException(
            status_code=422,
            detail="decision must be 'keep_enriched' or 'accept_sap'",
        )

    yaml_svc = _get_yaml_service()
    git_svc = _get_git_service()
    settings = get_settings()
    repo_root = Path(settings.repo_root).resolve()
    store = _get_conflict_store()
    enrich_store = _get_enrichments_store()

    try:
        node = yaml_svc.get_yaml(yaml_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Locate the conflict in the sidecar store.
    all_for_entity = store.list_for(yaml_id, include_resolved=True)
    conflict_raw: dict | None = next(
        (c for c in all_for_entity if c.get("id") == conflict_id),
        None,
    )
    if conflict_raw is None:
        raise HTTPException(
            status_code=404,
            detail=f"Conflict '{conflict_id}' not found in YAML '{yaml_id}'",
        )
    if conflict_raw.get("resolved"):
        raise HTTPException(
            status_code=409,
            detail=f"Conflict '{conflict_id}' is already resolved",
        )

    # Load the raw YAML — needed only if the resolution applies a value
    # change at the file level (accept_sap on a field or entity prop).
    abs_path = repo_root / node.file_path
    raw = load_yaml_text(abs_path.read_text(encoding="utf-8")) or {}
    is_bronze = node.layer.value == "bronze"

    field_name = conflict_raw["field_name"]
    conflict_type = conflict_raw.get("conflict_type") or ""
    is_entity_level = conflict_type == "entity_modified" or field_name == "__entity__"

    yaml_was_mutated = False
    enrichments_mutated = False

    if req.decision == "accept_sap":
        sap_value = conflict_raw.get("sap_value") or {}
        enriched_props = conflict_raw.get("enriched_properties") or []
        # Provenance lives in the ``.enrichments.json`` sidecar; the inline
        # ``_meta`` is only a legacy read-time fallback. The previous code
        # popped from ``_meta`` alone, so the sidecar kept the (now
        # relinquished) property and the very next SAP re-ingest re-raised the
        # identical conflict even though the change came from SAP and the admin
        # already accepted it. Clear the sidecar (the value the next merge
        # actually reads) AND scrub any lingering legacy ``_meta``.
        sc_entity_enr, sc_field_enr = enrich_store.read(yaml_id)
        if is_entity_level:
            for prop in enriched_props:
                if prop in sap_value:
                    raw[prop] = sap_value[prop]
            sc_entity_enr = sorted(set(sc_entity_enr) - set(enriched_props))
        elif conflict_type == "field_removed":
            # Accepting SAP on a removal conflict means DELETE the field —
            # sap_value is empty here (SAP no longer sends it), so overlaying
            # it would be a silent no-op that leaves the field alive.
            _remove_field(raw, field_name, is_bronze)
            if is_bronze:
                _resync_bronze_primary_key(raw)
            sc_field_enr = _drop_field_props(sc_field_enr, field_name, [])
            enriched_props = []  # scrub the whole field from legacy _meta too
        else:
            _apply_sap_value_to_field(raw, field_name, sap_value, is_bronze)
            sc_field_enr = _drop_field_props(sc_field_enr, field_name, enriched_props)
        enrich_store.write(
            yaml_id,
            entity_enrichments=sc_entity_enr,
            field_enrichments=sc_field_enr,
        )
        _scrub_legacy_meta(raw, field_name, enriched_props, is_entity_level)
        yaml_was_mutated = True
        enrichments_mutated = True
        # A removed Silver field can be a grain member / fan-out input — the
        # derived surface must follow (same derivation every write path runs).
        if conflict_type == "field_removed" and not is_bronze:
            _rederive_grain_and_fanout(raw, sc_field_enr)

    # Mark the conflict resolved in the sidecar store.
    now_iso = datetime.now(tz=UTC).isoformat()
    store.update_conflict(
        yaml_id,
        conflict_id,
        {
            "resolved": True,
            "resolution": req.decision,
            "resolved_by": _user.email,
            "resolved_at": now_iso,
        },
    )

    paths_to_commit: list[str] = []
    if yaml_was_mutated:
        abs_path.write_text(AskYamlSerializer().to_yaml(raw), encoding="utf-8")
        # Direct write — the service cache must not serve the pre-resolve file
        # for the rest of the signature TTL window.
        yaml_svc.invalidate_cache()
        paths_to_commit.append(node.file_path)
    # Sidecar path is also committed so the resolution is in git history.
    sidecar_abs = store._path(yaml_id)  # noqa: SLF001 — same package
    try:
        paths_to_commit.append(sidecar_abs.relative_to(repo_root).as_posix())
    except ValueError:
        pass
    # When accept_sap relinquished a property, the enrichments sidecar changed
    # (or was removed) — commit it too so the cleared provenance does not
    # linger as a dirty tracked file (which later aborts the publish branch
    # switch). _stage tolerates the deleted-when-empty case.
    if enrichments_mutated:
        enr_abs = enrich_store._path(yaml_id)  # noqa: SLF001 — same package
        try:
            paths_to_commit.append(enr_abs.relative_to(repo_root).as_posix())
        except ValueError:
            pass

    git_svc.commit(
        paths_to_commit,
        f"merge({yaml_id}): resolve {field_name} [{req.decision}]",
        _user.email.split("@")[0],
        _user.email,
    )

    # After this resolution, are there any pending conflicts left?
    remaining = store.list_for(yaml_id, include_resolved=False)
    if not remaining:
        _handle_all_conflicts_resolved(
            yaml_id=yaml_id,
            node=yaml_svc.get_yaml(yaml_id),
            raw=raw,
            abs_path=abs_path,
            repo_root=repo_root,
            settings=settings,
            store=store,
            yaml_svc=yaml_svc,
            git_svc=git_svc,
            author_email=_user.email,
        )

    return yaml_svc.get_yaml(yaml_id)


@router.post("/yamls/{yaml_id}/conflicts/resolve-bulk", response_model=VizYAMLNode)
async def resolve_conflicts_bulk(
    yaml_id: str,
    req: BulkConflictResolutionRequest,
    _user: TokenClaims = Depends(validate_token),
) -> VizYAMLNode:
    """Resolve many conflicts of one entity in a single pass.

    Same semantics per item as the single endpoint (keep_enriched preserves,
    accept_sap applies + relinquishes provenance), but ONE YAML write, ONE
    enrichments-sidecar write and ONE commit — the fast path the upload-first
    flow needs when a whole export's differences land at once.
    """
    if not req.resolutions:
        raise HTTPException(status_code=422, detail="resolutions must be non-empty")
    for item in req.resolutions:
        if item.decision not in ("keep_enriched", "accept_sap"):
            raise HTTPException(
                status_code=422,
                detail=f"decision must be 'keep_enriched' or 'accept_sap' "
                f"(conflict '{item.conflict_id}')",
            )

    yaml_svc = _get_yaml_service()
    git_svc = _get_git_service()
    settings = get_settings()
    repo_root = Path(settings.repo_root).resolve()
    store = _get_conflict_store()
    enrich_store = _get_enrichments_store()

    try:
        node = yaml_svc.get_yaml(yaml_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    all_for_entity = store.list_for(yaml_id, include_resolved=True)
    by_id = {c.get("id"): c for c in all_for_entity}
    # Validate the whole batch BEFORE mutating anything — a partial bulk apply
    # would leave the admin unsure which half landed.
    for item in req.resolutions:
        conflict = by_id.get(item.conflict_id)
        if conflict is None:
            raise HTTPException(
                status_code=404,
                detail=f"Conflict '{item.conflict_id}' not found in YAML '{yaml_id}'",
            )
        if conflict.get("resolved"):
            raise HTTPException(
                status_code=409,
                detail=f"Conflict '{item.conflict_id}' is already resolved",
            )

    abs_path = repo_root / node.file_path
    raw = load_yaml_text(abs_path.read_text(encoding="utf-8")) or {}
    is_bronze = node.layer.value == "bronze"

    sc_entity_enr, sc_field_enr = enrich_store.read(yaml_id)
    yaml_was_mutated = False
    enrichments_mutated = False
    removed_silver_field = False
    now_iso = datetime.now(tz=UTC).isoformat()

    for item in req.resolutions:
        conflict_raw = by_id[item.conflict_id]
        field_name = conflict_raw["field_name"]
        conflict_type = conflict_raw.get("conflict_type") or ""
        is_entity_level = conflict_type == "entity_modified" or field_name == "__entity__"

        if item.decision == "accept_sap":
            sap_value = conflict_raw.get("sap_value") or {}
            enriched_props = conflict_raw.get("enriched_properties") or []
            if is_entity_level:
                for prop in enriched_props:
                    if prop in sap_value:
                        raw[prop] = sap_value[prop]
                sc_entity_enr = sorted(set(sc_entity_enr) - set(enriched_props))
            elif conflict_type == "field_removed":
                # Accept SAP on a removal = DELETE the field (sap_value is
                # empty; overlaying it would silently keep the field alive).
                _remove_field(raw, field_name, is_bronze)
                if is_bronze:
                    _resync_bronze_primary_key(raw)
                sc_field_enr = _drop_field_props(sc_field_enr, field_name, [])
                enriched_props = []
                removed_silver_field = removed_silver_field or not is_bronze
            else:
                _apply_sap_value_to_field(raw, field_name, sap_value, is_bronze)
                sc_field_enr = _drop_field_props(sc_field_enr, field_name, enriched_props)
            _scrub_legacy_meta(raw, field_name, enriched_props, is_entity_level)
            yaml_was_mutated = True
            enrichments_mutated = True

        store.update_conflict(
            yaml_id,
            item.conflict_id,
            {
                "resolved": True,
                "resolution": item.decision,
                "resolved_by": _user.email,
                "resolved_at": now_iso,
            },
        )

    if enrichments_mutated:
        enrich_store.write(
            yaml_id, entity_enrichments=sc_entity_enr, field_enrichments=sc_field_enr
        )
    # Removed Silver fields can be grain members / fan-out inputs — re-derive
    # ONCE for the whole batch (same derivation every write path runs).
    if removed_silver_field:
        _rederive_grain_and_fanout(raw, sc_field_enr)

    paths_to_commit: list[str] = []
    if yaml_was_mutated:
        abs_path.write_text(AskYamlSerializer().to_yaml(raw), encoding="utf-8")
        yaml_svc.invalidate_cache()
        paths_to_commit.append(node.file_path)
    sidecar_abs = store._path(yaml_id)  # noqa: SLF001 — same package
    try:
        paths_to_commit.append(sidecar_abs.relative_to(repo_root).as_posix())
    except ValueError:
        pass
    if enrichments_mutated:
        enr_abs = enrich_store._path(yaml_id)  # noqa: SLF001 — same package
        try:
            paths_to_commit.append(enr_abs.relative_to(repo_root).as_posix())
        except ValueError:
            pass

    accepted = sum(1 for i in req.resolutions if i.decision == "accept_sap")
    kept = len(req.resolutions) - accepted
    git_svc.commit(
        paths_to_commit,
        f"merge({yaml_id}): bulk-resolve {len(req.resolutions)} conflicts "
        f"[{accepted} accept_sap, {kept} keep_enriched]",
        _user.email.split("@")[0],
        _user.email,
    )

    remaining = store.list_for(yaml_id, include_resolved=False)
    if not remaining:
        _handle_all_conflicts_resolved(
            yaml_id=yaml_id,
            node=yaml_svc.get_yaml(yaml_id),
            raw=raw,
            abs_path=abs_path,
            repo_root=repo_root,
            settings=settings,
            store=store,
            yaml_svc=yaml_svc,
            git_svc=git_svc,
            author_email=_user.email,
        )

    return yaml_svc.get_yaml(yaml_id)


def _handle_all_conflicts_resolved(
    yaml_id: str,
    node: VizYAMLNode,
    raw: dict,
    abs_path: Path,
    repo_root: Path,
    settings,
    store: ConflictStore,
    yaml_svc: YAMLFileService,
    git_svc: GitService,
    author_email: str,
) -> None:
    """Snapshot SAP's resolved values into the baseline, then drop the
    sidecar file. Mirrors the previous _meta.conflicts cleanup but the
    state lives in the sidecar JSON instead of inside the YAML."""
    # Sap_merge_service writes the baseline at the END of every merge (not
    # just conflict-free ones) so it always reflects the latest SAP state.
    # Once every conflict on this entity is resolved, the baseline is
    # already correct for SAP — no reconstruction needed here. We just
    # drop the sidecar so the entity stops appearing in the Pending
    # Conflicts inbox.
    sidecar_path = store._path(yaml_id)  # noqa: SLF001 — same package
    sidecar_existed = sidecar_path.exists()
    store.clear_resolved(yaml_id)

    # Commit the sidecar removal so the audit trail captures the
    # all-resolved transition. Skip if the file never existed in this
    # repo's git history (clear_resolved deletes it; ``git add`` on a
    # missing path would error).
    if sidecar_existed:
        try:
            sidecar_rel = sidecar_path.relative_to(repo_root).as_posix()
            git_svc.commit(
                [sidecar_rel],
                f"merge({yaml_id}): all conflicts resolved",
                author_email.split("@")[0],
                author_email,
            )
        except (ValueError, Exception):  # noqa: BLE001 — audit-only
            logger.warning("Could not commit sidecar removal for %s", yaml_id)
