"""Pydantic models for the first-class DataProduct lifecycle.

A ``DataProduct`` = one silver/gold YAML entity. Its lifecycle metadata
(status, version, dev/prod publish records) is **denormalized** into the
dedicated ``ask-entity-lifecycle-v1`` index — never inside the YAML body and
never inside the ``BusinessDomain`` doc.

Why a dedicated index (UX_CHANGES audit §5.1): computing status from git on
every catalog read is too expensive (~200 entities × 3 git rev-parses per page
load). This index mirrors the lifecycle state and is updated only on the 5
events that can change it (audit §5.3).

Env separation (dev/prod indices, dev/prod DB) lands in Iter 2. For Iter 1 the
doc already carries both ``dev_published`` and ``prod_published`` fields, but
the single existing publish flow only ever writes ``dev_published`` (default
``dev`` target, audit §9 / decision C).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .workspaces import now_iso

# Status pill enum (audit §5.4). "In Review" = working definition differs from
# what's deployed to dev; "Released" = working == dev.
DataProductStatus = Literal["In Review", "Released"]


class PublishRecord(BaseModel):
    """One published snapshot of a DataProduct on an environment branch."""

    version: int
    sha: str  # git sha of the file on the published branch
    at: str  # ISO timestamp
    by: str  # author email


class DataProductLifecycle(BaseModel):
    """Stored shape in ``ask-entity-lifecycle-v1`` (one doc per DataProduct).

    The doc id IS the ``entity_id`` (1:1 with a YAML id), so reads are a single
    ``GET _doc/<entity_id>``.
    """

    entity_id: str
    workspace_id: str = ""
    # Reverse index: which Business Domains reference this DP. Denormalized
    # (audit §10.1) — kept in sync when BD membership changes.
    business_domain_ids: list[str] = Field(default_factory=list)

    status: DataProductStatus = "In Review"
    version: int = 1

    main_sha: str = ""
    dev_published: PublishRecord | None = None
    prod_published: PublishRecord | None = None

    updated_at: str = ""


class CatalogRow(DataProductLifecycle):
    """Catalog / lifecycle READ shape = the stored lifecycle doc plus a derived
    ``pending_conflicts`` count.

    ``pending_conflicts`` is an *orthogonal attribute*, NOT a lifecycle status:
    a conflicted entity is already ``In Review`` (the SAP merge that produced the
    conflict set it), but ``In Review`` does not imply a conflict. The count is
    computed per read from the conflict sidecars — never persisted into the
    lifecycle index — so the status enum stays a single concern (audit §5.4) and
    future blocking conditions (validation, stale-vs-source, locks) can be added
    the same way without status churn.
    """

    pending_conflicts: int = 0


def compute_status(main_sha: str, dev_published: PublishRecord | None) -> DataProductStatus:
    """Status rule (audit §5.4), cached at write time.

    ``Released`` iff the working definition (main) equals what's deployed to
    dev; otherwise ``In Review``. Whether prod trails dev affects the
    deployment panel UI, not the status pill.
    """
    if dev_published is not None and dev_published.sha and main_sha == dev_published.sha:
        return "Released"
    return "In Review"


def new_lifecycle_doc(
    entity_id: str,
    *,
    workspace_id: str = "",
    business_domain_ids: list[str] | None = None,
    main_sha: str = "",
) -> DataProductLifecycle:
    """Factory for a freshly-created DP (audit §5.3, "Create" trigger)."""
    return DataProductLifecycle(
        entity_id=entity_id,
        workspace_id=workspace_id,
        business_domain_ids=list(business_domain_ids or []),
        status="In Review",
        version=1,
        main_sha=main_sha,
        dev_published=None,
        prod_published=None,
        updated_at=now_iso(),
    )


__all__ = [
    "CatalogRow",
    "DataProductLifecycle",
    "DataProductStatus",
    "PublishRecord",
    "compute_status",
    "new_lifecycle_doc",
]
