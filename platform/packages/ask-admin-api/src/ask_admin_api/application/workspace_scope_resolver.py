"""Resolve a workspace into the set of entity ids the SPA should see.

Workspaces hold one or more Business Domains. Each BD carries a
``data_product_ids`` list (the canonical scope used by the chat). For the admin
SPA's Graph / Knowledge / Merge views we want the SAME core scope PLUS the
nearest neighbors the admin needs to make sense of those entities:

  * ``composed_of`` bronzes — silver/gold YAMLs reference their source
    bronzes either by entity id (e.g. ``["bronze_s4h_vbak_order_header"]``,
    the form curated/ingested YAMLs carry) or by raw SAP table name (legacy,
    e.g. ``["VBAK", "VBAP"]``). We resolve both to the bronze entity id.
  * ``relationships[*].target_entity`` — direct edges in the lineage graph.
    Useful because the admin almost always wants to see the dimension a
    fact joins to.

We expand ONE hop only (no recursive transitive closure) — that matches
the typical "scope this workspace" mental model without dragging in the
entire catalogue.

Public surface:

  * ``resolve_workspace_scope(workspace_slug_or_id, yaml_service)`` →
    ``set[str]`` of entity ids that belong to the workspace.
  * ``resolve_domain_scope(business_domain_id, yaml_service)`` →
    ``set[str]`` for a SINGLE Business Domain's canvas (its ``data_product_ids``
    + the same one-hop expansion). A domain is a subset of its workspace; the
    expansion logic is shared via ``_expand``.
"""

from __future__ import annotations

import logging
from typing import Any

from .workspace_repository import WorkspaceRepository
from .workspace_service import (
    BusinessDomainNotFoundError,
    WorkspaceNotFoundError,
    WorkspaceService,
)
from .yaml_file_service import YAMLFileService

logger = logging.getLogger(__name__)


class WorkspaceScopeError(Exception):
    """Raised when the workspace cannot be resolved."""


def resolve_workspace_scope(
    workspace_id_or_slug: str,
    yaml_service: YAMLFileService,
    *,
    workspace_service: WorkspaceService | None = None,
) -> set[str]:
    """Return the full set of entity ids the admin SPA should show for ``workspace``.

    Raises :class:`WorkspaceScopeError` when the workspace does not exist.
    Returns an empty set when the workspace exists but has zero entity_ids
    across its data products — caller renders an empty-state.
    """
    svc = workspace_service or WorkspaceService(WorkspaceRepository())

    try:
        workspace = svc.get_workspace(workspace_id_or_slug)
    except WorkspaceNotFoundError as exc:
        raise WorkspaceScopeError(str(exc)) from exc

    bds = svc.list_business_domains(workspace.id)

    core: set[str] = set()
    for bd in bds:
        for entity_id in bd.data_product_ids or []:
            if entity_id:
                core.add(entity_id)

    return _expand(core, yaml_service)


def resolve_domain_scope(
    business_domain_id: str,
    yaml_service: YAMLFileService,
    *,
    workspace_service: WorkspaceService | None = None,
) -> set[str]:
    """Return the entity ids for a single Business Domain's canvas — STRICT membership.

    The domain canvas (design-spec §03) is scoped to ONE BD by **strict
    membership**: its ``data_product_ids`` + each member's ``composed_of``
    bronzes (so a Silver/Gold renders with its nested bronze detail). Unlike
    :func:`resolve_workspace_scope`, relationship-target neighbors are
    **excluded** (``include_relationships=False``) — the canvas shows only what
    is actually in the domain, so adding/removing a Data Product maps 1:1 to
    what appears (a member's relationship to a NON-member doesn't drag the
    non-member onto the canvas). Relationships BETWEEN members still render as
    edges, because both endpoints are in scope.

    ``business_domain_id`` is the BD **id** (resolution is by id; BD slugs are
    only unique within a workspace). Raises :class:`WorkspaceScopeError` when the
    Business Domain does not exist. Returns an empty set when it has zero
    ``data_product_ids`` — caller renders an empty-state.
    """
    svc = workspace_service or WorkspaceService(WorkspaceRepository())

    try:
        bd = svc.get_business_domain(business_domain_id)
    except BusinessDomainNotFoundError as exc:
        raise WorkspaceScopeError(str(exc)) from exc

    core = {eid for eid in (bd.data_product_ids or []) if eid}
    return _expand(core, yaml_service, include_relationships=False)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _expand(
    core: set[str],
    yaml_service: YAMLFileService,
    *,
    include_relationships: bool = True,
) -> set[str]:
    """Expand a core entity-id set by ONE hop — shared by workspace + domain scope.

    Adds, for each core entity, its ``composed_of`` bronzes (referenced by
    bronze id or by SAP table name — both resolved to the bronze id). When
    ``include_relationships`` is True it ALSO adds
    ``relationships[].target_entity`` neighbors — the workspace view wants that
    context; the domain canvas passes ``False`` for strict membership (only
    members + their own bronzes). Returns the empty set for an empty core.
    """
    if not core:
        return set()

    # Build the indices once — _iter_yaml_files() rglobs the disk and parses
    # YAMLs lazily; we cache the projection here so the expansion does at most
    # one full pass.
    by_id, name_to_bronze_id = _build_indices(yaml_service)

    expanded: set[str] = set(core)
    for entity_id in core:
        raw = by_id.get(entity_id)
        if raw is None:
            # Entity referenced by a DP but not present in the workspace folder.
            # Skip silently — the SPA will flag the orphan elsewhere if it cares.
            continue

        # composed_of: bronze references in EITHER convention —
        #   * the bronze entity id directly (e.g. "bronze_s4h_marc_plant_material"),
        #     which is what ingested/curated YAMLs actually carry; or
        #   * the raw SAP table name (legacy, e.g. "VBAK").
        # Resolve a direct bronze-id hit first, then fall back to the name lookup.
        for ref in raw.get("composed_of") or []:
            if not isinstance(ref, str) or not ref:
                continue
            direct = by_id.get(ref)
            if direct is not None and direct.get("layer") == "bronze":
                expanded.add(ref)
                continue
            bronze_id = name_to_bronze_id.get(ref.upper())
            if bronze_id:
                expanded.add(bronze_id)

        # relationships[].target_entity: direct neighbors (silver↔silver, silver↔gold).
        # Workspace scope only — the domain canvas is strict membership.
        if include_relationships:
            for rel in raw.get("relationships") or []:
                if not isinstance(rel, dict):
                    continue
                target = rel.get("target_entity")
                if isinstance(target, str) and target:
                    expanded.add(target)

    return expanded


def _build_indices(yaml_service: YAMLFileService) -> tuple[dict[str, Any], dict[str, str]]:
    """Walk the workspace once and return two lookup tables.

    Returns ``(by_id, name_to_bronze_id)``. The bronze-name lookup is built
    only from bronze YAMLs so silver/gold ``name`` collisions don't override
    it (the spec is unambiguous: ``composed_of`` references SAP table names,
    which only bronzes carry).
    """
    by_id: dict[str, Any] = {}
    name_to_bronze: dict[str, str] = {}
    for yaml_file in yaml_service._iter_yaml_files():  # noqa: SLF001 — service-internal
        try:
            raw = yaml_service._load_raw(yaml_file)  # noqa: SLF001
        except Exception:  # noqa: BLE001 — keep walking on malformed files
            continue
        if not isinstance(raw, dict):
            continue
        entity_id = raw.get("id")
        if not isinstance(entity_id, str) or not entity_id:
            continue
        by_id[entity_id] = raw
        if raw.get("layer") == "bronze":
            name = raw.get("name")
            if isinstance(name, str) and name:
                name_to_bronze[name.upper()] = entity_id
    return by_id, name_to_bronze
