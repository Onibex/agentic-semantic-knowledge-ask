"""DataProduct lifecycle service — the 5 triggers + status calc + rebuild.

This owns the ``ask-entity-lifecycle-v1`` denormalized state. Five events can
change a DP's lifecycle (UX_CHANGES audit §5.3):

  1. on_create      — a new DP appears (manual / DDL / OneConnect / SAP merge)
  2. on_edit        — the working YAML is edited (manual save / AI Assist apply)
  3. on_sap_merge   — a SAP merge updates the working YAML (same effect as edit)
  4. on_publish_dev — the working version is cut + deployed to dev
  5. on_publish_prod— the dev version is promoted to prod

Version semantics (audit §5.3 — authoritative over the §4.1 summary):
  ``version`` is the version number of the *working* definition. It increments
  on the first edit *after* a release (Released → In Review). On Publish to dev
  the current working ``version`` is recorded into ``dev_published``; the
  counter is NOT bumped again at publish time. This reproduces the audit's §5.2
  snapshot (version=4 while In Review, dev_published.version=3).

``main_sha`` is a *content marker* that changes only on create/edit/merge.
Publish copies the current ``main_sha`` into ``dev_published.sha`` (audit §5.3:
``sha=main_sha``) so that immediately after a publish ``main_sha ==
dev_published.sha`` → status ``Released``. The audit-only empty commit that
Publish writes must NOT feed ``main_sha`` (it would spuriously flip status back
to In Review). Real per-file git shas replace the marker in Iter 3.
"""

from __future__ import annotations

import logging
import uuid

from ..models.data_products import (
    DataProductLifecycle,
    PublishRecord,
    compute_status,
    new_lifecycle_doc,
)
from ..models.workspaces import BusinessDomain, now_iso
from .lifecycle_repository import LifecycleRepository

logger = logging.getLogger(__name__)


class PublishNotReadyError(RuntimeError):
    """Raised when Publish to prod is attempted before a dev publish exists."""


def _new_marker() -> str:
    """A fresh content marker for ``main_sha`` (Iter 1; git sha in Iter 3)."""
    return uuid.uuid4().hex


class LifecycleService:
    def __init__(self, repo: LifecycleRepository | None = None) -> None:
        self._repo = repo or LifecycleRepository()

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get(self, entity_id: str) -> DataProductLifecycle | None:
        return self._repo.get(entity_id)

    def list_all(self) -> list[DataProductLifecycle]:
        return self._repo.list_all()

    def list_by_workspace(self, workspace_id: str) -> list[DataProductLifecycle]:
        return self._repo.list_by_workspace(workspace_id)

    # ── Triggers ────────────────────────────────────────────────────────────────

    def on_create(
        self,
        entity_id: str,
        *,
        workspace_id: str = "",
        business_domain_ids: list[str] | None = None,
        main_sha: str | None = None,
    ) -> DataProductLifecycle:
        """A new DP appears. Idempotent: if a doc already exists, treat as edit."""
        existing = self._repo.get(entity_id)
        if existing is not None:
            return self.on_edit(entity_id, main_sha=main_sha)
        doc = new_lifecycle_doc(
            entity_id,
            workspace_id=workspace_id,
            business_domain_ids=business_domain_ids,
            main_sha=main_sha or _new_marker(),
        )
        return self._repo.upsert(doc)

    def on_edit(self, entity_id: str, *, main_sha: str | None = None) -> DataProductLifecycle:
        """The working YAML changed. Bumps version iff it was Released."""
        doc = self._repo.get(entity_id) or new_lifecycle_doc(entity_id)
        was_released = doc.status == "Released"
        doc.main_sha = main_sha or _new_marker()
        if was_released:
            doc.version += 1
        doc.status = compute_status(doc.main_sha, doc.dev_published)
        doc.updated_at = now_iso()
        return self._repo.upsert(doc)

    def on_sap_merge(self, entity_id: str, *, main_sha: str | None = None) -> DataProductLifecycle:
        """A SAP merge updated the working YAML — same effect as an edit."""
        return self.on_edit(entity_id, main_sha=main_sha)

    def on_publish_dev(
        self,
        entity_id: str,
        *,
        by: str,
        at: str | None = None,
    ) -> DataProductLifecycle:
        """Cut the working version + deploy it to dev. Status → Released."""
        doc = self._repo.get(entity_id) or new_lifecycle_doc(entity_id, main_sha=_new_marker())
        doc.dev_published = PublishRecord(
            version=doc.version,
            sha=doc.main_sha,
            at=at or now_iso(),
            by=by,
        )
        doc.status = compute_status(doc.main_sha, doc.dev_published)
        doc.updated_at = now_iso()
        return self._repo.upsert(doc)

    def on_publish_prod(
        self,
        entity_id: str,
        *,
        by: str,
        at: str | None = None,
    ) -> DataProductLifecycle:
        """Promote the dev version to prod. Status stays Released; no version bump.

        Env separation lands in Iter 2 — this is wired but not reachable from the
        single Iter-1 publish flow (which targets dev by default, decision C).
        """
        doc = self._repo.get(entity_id)
        if doc is None or doc.dev_published is None:
            raise PublishNotReadyError(
                f"Cannot publish '{entity_id}' to prod before a dev publish exists."
            )
        doc.prod_published = PublishRecord(
            version=doc.dev_published.version,
            sha=doc.dev_published.sha,
            at=at or now_iso(),
            by=by,
        )
        doc.updated_at = now_iso()
        return self._repo.upsert(doc)

    def on_unpublish_dev(self, entity_id: str, *, by: str) -> DataProductLifecycle:
        """Remove the entity from dev (inverse of on_publish_dev).

        Clears ``dev_published``; status recomputes against an empty dev record
        (→ In Review). The prod-before-dev gate lives in ``PublishService`` (a
        prod publish depends on dev's lineage), so this is a pure state clear.
        ``by`` is accepted for call-site symmetry / future audit; the record is
        removed, not stamped.
        """
        doc = self._repo.get(entity_id)
        if doc is None:
            raise PublishNotReadyError(f"'{entity_id}' has no lifecycle record to unpublish.")
        doc.dev_published = None
        doc.status = compute_status(doc.main_sha, doc.dev_published)
        doc.updated_at = now_iso()
        return self._repo.upsert(doc)

    def on_unpublish_prod(self, entity_id: str, *, by: str) -> DataProductLifecycle:
        """Remove the entity from prod (inverse of on_publish_prod).

        Clears ``prod_published`` only; ``status`` derives from ``dev_published``
        so it is unaffected. ``dev_published`` is left intact — the entity stays
        answerable in dev.
        """
        doc = self._repo.get(entity_id)
        if doc is None:
            raise PublishNotReadyError(f"'{entity_id}' has no lifecycle record to unpublish.")
        doc.prod_published = None
        doc.updated_at = now_iso()
        return self._repo.upsert(doc)

    # ── Reverse index (business_domain_ids) ──────────────────────────────────

    def recompute_membership(
        self,
        entity_ids: set[str],
        all_business_domains: list[BusinessDomain],
    ) -> None:
        """Recompute the ``business_domain_ids`` reverse index for ``entity_ids``.

        Called after any BD membership change (create / update / delete). For a
        DP that has no lifecycle doc yet (e.g. a pre-existing YAML referenced by
        a BD for the first time) this seeds one — status In Review, version 1.

        A DP can belong to BDs in multiple workspaces (N:N). The single
        ``workspace_id`` field stores the first containing BD's workspace; the
        cross-workspace case is a documented v1 limitation.
        """
        for eid in entity_ids:
            containing = [bd for bd in all_business_domains if eid in (bd.data_product_ids or [])]
            doc = self._repo.get(eid) or new_lifecycle_doc(eid, main_sha=_new_marker())
            doc.business_domain_ids = [bd.id for bd in containing]
            if containing:
                doc.workspace_id = containing[0].workspace_id
            doc.updated_at = now_iso()
            self._repo.upsert(doc)

    # ── Reconciliation (audit §5.6) ────────────────────────────────────────────

    def rebuild(self, all_business_domains: list[BusinessDomain]) -> int:
        """Reseed the lifecycle index membership from current Business Domains.

        Iter 1 scope: ensure a lifecycle doc exists for every DP referenced by a
        BD and that ``business_domain_ids`` / ``workspace_id`` match reality.
        Existing status / version / publish records are preserved. Full git-based
        reconciliation (recomputing version + status from per-file shas) lands
        with the git-flow in Iter 3.

        Returns the number of lifecycle docs touched.
        """
        all_entity_ids: set[str] = set()
        for bd in all_business_domains:
            for eid in bd.data_product_ids or []:
                if eid:
                    all_entity_ids.add(eid)
        self.recompute_membership(all_entity_ids, all_business_domains)
        return len(all_entity_ids)
