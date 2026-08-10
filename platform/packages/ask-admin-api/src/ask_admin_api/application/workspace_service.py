"""Business logic for Workspaces, Business Domains, and Organization.

Sits between the FastAPI routers and the OpenSearch repository.

Responsibilities:
  * Slug uniqueness — enforced at the service layer with search-then-write.
  * Cascade delete — workspace removal also drops its business domains.
  * Timestamps + author stamping — single source of truth (router never sets
    these directly; passes the caller email).
  * Lookup-by-id-or-slug — every endpoint accepts either, the service
    transparently resolves.

``BusinessDomain`` was formerly ``DataProduct`` (UX_CHANGES audit, Iter 1).
The per-DP lifecycle (status/version/publish) lives in a separate service +
index — this service only owns the workspace → business-domain hierarchy.

Concurrency note: the slug uniqueness check has a tiny TOCTOU race window.
For the "10 workspaces, one admin at a time" volume we target this is fine.
If we ever need stricter guarantees the repo can adopt OpenSearch's
external-version optimistic locking.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models.workspaces import (
    BusinessDomain,
    BusinessDomainCreate,
    BusinessDomainUpdate,
    Organization,
    OrganizationUpdate,
    Workspace,
    WorkspaceCreate,
    WorkspaceUpdate,
    now_iso,
)
from .workspace_repository import WorkspaceRepository

logger = logging.getLogger(__name__)


# ── Domain errors — caught by the router and mapped to HTTP status codes ───


class WorkspaceNotFoundError(LookupError):
    pass


class BusinessDomainNotFoundError(LookupError):
    pass


class SlugConflictError(ValueError):
    """Raised when the requested slug is already taken in the relevant scope.

    For workspaces the scope is global. For business domains it's per-workspace
    (two workspaces can each have a BD named ``orders``).
    """


# ── Service ────────────────────────────────────────────────────────────────


class WorkspaceService:
    def __init__(self, repo: WorkspaceRepository | None = None) -> None:
        self._repo = repo or WorkspaceRepository()

    # ── Workspaces ─────────────────────────────────────────────────────────

    def list_workspaces(self) -> list[Workspace]:
        return self._repo.list_workspaces()

    def get_workspace(self, id_or_slug: str) -> Workspace:
        ws = self._resolve_workspace(id_or_slug)
        if ws is None:
            raise WorkspaceNotFoundError(id_or_slug)
        return ws

    def create_workspace(self, body: WorkspaceCreate, *, author_email: str) -> Workspace:
        # Slug uniqueness check first — fail fast before generating UUIDs.
        if self._repo.get_workspace_by_slug(body.slug) is not None:
            raise SlugConflictError(f"Workspace slug '{body.slug}' already exists.")

        now = now_iso()
        doc: dict[str, Any] = {
            "slug": body.slug,
            "name": body.name,
            "objective": body.objective,
            "description": body.description,
            "roles": [r.model_dump() for r in body.roles],
            "created_at": now,
            "created_by": author_email,
            "updated_at": now,
            "updated_by": author_email,
        }
        return self._repo.create_workspace(doc)

    def update_workspace(
        self,
        id_or_slug: str,
        body: WorkspaceUpdate,
        *,
        author_email: str,
    ) -> Workspace:
        current = self.get_workspace(id_or_slug)

        # Slug change → recheck uniqueness against everyone EXCEPT this workspace.
        if body.slug and body.slug != current.slug:
            collision = self._repo.get_workspace_by_slug(body.slug)
            if collision is not None and collision.id != current.id:
                raise SlugConflictError(f"Workspace slug '{body.slug}' already exists.")

        merged: dict[str, Any] = {
            "slug": body.slug if body.slug is not None else current.slug,
            "name": body.name if body.name is not None else current.name,
            "objective": body.objective if body.objective is not None else current.objective,
            "description": (
                body.description if body.description is not None else current.description
            ),
            "roles": (
                [r.model_dump() for r in body.roles]
                if body.roles is not None
                else [r.model_dump() for r in current.roles]
            ),
            "created_at": current.created_at,
            "created_by": current.created_by,
            "updated_at": now_iso(),
            "updated_by": author_email,
        }
        return self._repo.update_workspace(current.id, merged)

    def delete_workspace(self, id_or_slug: str) -> dict[str, int]:
        """Cascade delete — workspace + all its business domains. Returns counts."""
        current = self.get_workspace(id_or_slug)
        bds_deleted = self._repo.delete_business_domains_by_workspace(current.id)
        ws_deleted = self._repo.delete_workspace(current.id)
        logger.info(
            "Deleted workspace %s (%s) + %d business domains",
            current.id,
            current.slug,
            bds_deleted,
        )
        return {
            "workspaces_deleted": 1 if ws_deleted else 0,
            "business_domains_deleted": bds_deleted,
        }

    # ── Business Domains ───────────────────────────────────────────────────

    def list_business_domains(self, ws_id_or_slug: str) -> list[BusinessDomain]:
        ws = self.get_workspace(ws_id_or_slug)
        return self._repo.list_business_domains_by_workspace(ws.id)

    def list_all_business_domains(self) -> list[BusinessDomain]:
        """Every BD across all workspaces — used to rebuild the DP reverse index."""
        return self._repo.list_all_business_domains()

    def get_business_domain(self, bd_id: str) -> BusinessDomain:
        bd = self._repo.get_business_domain(bd_id)
        if bd is None:
            raise BusinessDomainNotFoundError(bd_id)
        return bd

    def create_business_domain(
        self,
        ws_id_or_slug: str,
        body: BusinessDomainCreate,
        *,
        author_email: str,
    ) -> BusinessDomain:
        ws = self.get_workspace(ws_id_or_slug)
        # Per-workspace uniqueness — same slug in a different workspace is OK.
        if self._repo.get_business_domain_by_slug(ws.id, body.slug) is not None:
            raise SlugConflictError(
                f"Business domain slug '{body.slug}' already exists in workspace '{ws.slug}'."
            )

        now = now_iso()
        doc: dict[str, Any] = {
            "workspace_id": ws.id,
            "slug": body.slug,
            "name": body.name,
            "description": body.description,
            "data_product_ids": list(body.data_product_ids),
            "created_at": now,
            "created_by": author_email,
            "updated_at": now,
            "updated_by": author_email,
        }
        return self._repo.create_business_domain(doc)

    def update_business_domain(
        self,
        bd_id: str,
        body: BusinessDomainUpdate,
        *,
        author_email: str,
    ) -> BusinessDomain:
        current = self.get_business_domain(bd_id)

        if body.slug and body.slug != current.slug:
            collision = self._repo.get_business_domain_by_slug(current.workspace_id, body.slug)
            if collision is not None and collision.id != current.id:
                raise SlugConflictError(
                    f"Business domain slug '{body.slug}' already exists in this workspace."
                )

        merged: dict[str, Any] = {
            "workspace_id": current.workspace_id,
            "slug": body.slug if body.slug is not None else current.slug,
            "name": body.name if body.name is not None else current.name,
            "description": (
                body.description if body.description is not None else current.description
            ),
            "data_product_ids": (
                list(body.data_product_ids)
                if body.data_product_ids is not None
                else list(current.data_product_ids)
            ),
            "created_at": current.created_at,
            "created_by": current.created_by,
            "updated_at": now_iso(),
            "updated_by": author_email,
        }
        return self._repo.update_business_domain(current.id, merged)

    def add_data_product(self, bd_id: str, entity_id: str, *, author_email: str) -> BusinessDomain:
        """Atomically add ONE entity to a BD's membership (add-if-absent).

        The incremental counterpart of ``update_business_domain``'s full-array
        replace — the SPA's "+"/drag uses this so a burst of rapid adds can't
        lose updates (each is an atomic server-side scripted update; concurrent
        adds are commutative). Idempotent: re-adding a member is a no-op.
        """
        bd = self._repo.add_data_product(bd_id, entity_id, now=now_iso(), updated_by=author_email)
        if bd is None:
            raise BusinessDomainNotFoundError(bd_id)
        return bd

    def remove_data_product(
        self, bd_id: str, entity_id: str, *, author_email: str
    ) -> BusinessDomain:
        """Atomically drop ONE entity from a BD's membership (idempotent)."""
        bd = self._repo.remove_data_product(
            bd_id, entity_id, now=now_iso(), updated_by=author_email
        )
        if bd is None:
            raise BusinessDomainNotFoundError(bd_id)
        return bd

    def delete_business_domain(self, bd_id: str) -> bool:
        return self._repo.delete_business_domain(bd_id)

    # ── Workspace scope (for the chat retrieval filter) ───────────────────

    def get_workspace_entity_ids(self, ws_id_or_slug: str) -> list[str]:
        """Flat list of data product ids across all BDs of a workspace.

        Used to scope retrieval. Deduplicated because a DP can legitimately be
        in multiple BDs of the same workspace (typical for shared masters like
        ``customer_master``).
        """
        ws = self.get_workspace(ws_id_or_slug)
        seen: set[str] = set()
        result: list[str] = []
        for bd in self._repo.list_business_domains_by_workspace(ws.id):
            for eid in bd.data_product_ids:
                if eid not in seen:
                    seen.add(eid)
                    result.append(eid)
        return result

    def remove_data_product_everywhere(self, entity_id: str) -> int:
        """Remove ``entity_id`` from every Business Domain's ``data_product_ids``.

        Part of the full DataProduct delete so a deleted entity stops appearing
        on any domain canvas / membership list. Returns the number of domains
        updated. ``update_business_domain`` does a full replace, so we rebuild
        the whole doc with the filtered membership."""
        count = 0
        for bd in self._repo.list_all_business_domains():
            if entity_id in (bd.data_product_ids or []):
                doc = {
                    "workspace_id": bd.workspace_id,
                    "slug": bd.slug,
                    "name": bd.name,
                    "description": bd.description,
                    "data_product_ids": [x for x in bd.data_product_ids if x != entity_id],
                    "created_at": bd.created_at,
                    "created_by": bd.created_by,
                    "updated_at": now_iso(),
                    "updated_by": "system:delete",
                }
                self._repo.update_business_domain(bd.id, doc)
                count += 1
        return count

    # ── Organization (singleton) ──────────────────────────────────────────

    def get_organization(self) -> Organization:
        return self._repo.get_organization()

    def upsert_organization(
        self,
        body: OrganizationUpdate,
        *,
        author_email: str,
    ) -> Organization:
        # Normalize core_bases to uppercase + dedup, preserving order.
        seen: set[str] = set()
        core_bases: list[str] = []
        for b in body.core_bases:
            up = b.strip().upper()
            if up and up not in seen:
                seen.add(up)
                core_bases.append(up)

        # Prefer the generic source_system; fall back to legacy sap_version so a
        # client that still sends only sap_version keeps working. Mirror the
        # chosen value into both keys to keep old + new readers consistent.
        source_system = (body.source_system or body.sap_version or "").strip()
        doc = {
            "company_name": body.company_name.strip(),
            "source_system": source_system,
            "sap_version": source_system,
            "core_bases": core_bases,
            "url": body.url.strip(),
            "updated_at": now_iso(),
            "updated_by": author_email,
        }
        return self._repo.upsert_organization(doc)

    # ── Internals ─────────────────────────────────────────────────────────

    def _resolve_workspace(self, id_or_slug: str) -> Workspace | None:
        """Lookup that accepts either UUID or slug.

        UUIDs are 36 chars with 4 hyphens; slugs are <= 64 chars without that
        shape. We try by id first (cheap GET), fall back to slug search.
        """
        if "-" in id_or_slug and len(id_or_slug) == 36:
            ws = self._repo.get_workspace(id_or_slug)
            if ws is not None:
                return ws
        return self._repo.get_workspace_by_slug(id_or_slug)
