# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Pydantic models for Workspaces, Business Domains, and Organization.

These map 1:1 to OpenSearch documents in three indices:
  - ask-workspaces-v1
  - ask-business-domains-v1
  - ask-organization-v1

Vocabulary (UX_CHANGES audit, Iter 1):
  * ``BusinessDomain`` is an organizational grouping of Data Products. It was
    formerly called ``DataProduct``; the rename narrows its scope to "a folder
    of DPs". It holds ``data_product_ids`` — the entity ids (one silver/gold
    YAML each) that belong to it.
  * A ``DataProduct`` is now a first-class concept = one silver/gold YAML
    entity. Its lifecycle metadata (status, version, dev/prod publish) lives
    in the dedicated ``ask-entity-lifecycle-v1`` index (see
    models/data_products.py), never in this model.

Design decisions (locked in the Iter-1 debate):
  * Workspaces / BDs identified by UUID internally, slug for URLs / display.
  * Silvers + Golds + Bronzes are referenced by ID — they do NOT live inside
    a BD physically. A BD just enumerates which data_product_ids belong to it.
    Same DP can be in multiple BDs (N:N — typical for shared masters like
    customer_master).
  * Organization is a singleton (id="default") — this product is 1 deploy =
    1 customer, no multi-tenancy.
  * Cascade delete: removing a workspace removes its BDs (the service layer
    enforces this; the YAML files on disk are untouched).
  * Roles per workspace are informational only for now (no enforcement).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Helpers ─────────────────────────────────────────────────────────────────

# Slug rules: lowercase letters + digits + single-dash separators. Bounded
# length so URLs stay reasonable. Reserved-words list keeps a few obvious
# clashes out (we don't want /workspaces/new colliding with the new-button
# route in the SPA).
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG_RESERVED = {"new", "create", "edit", "delete", "default", "all"}


def _validate_slug(value: str) -> str:
    if not _SLUG_RE.match(value):
        raise ValueError(
            "Slug must be lowercase letters/digits separated by single hyphens "
            "(e.g. 'sales-and-operations')."
        )
    if value in _SLUG_RESERVED:
        raise ValueError(f"Slug '{value}' is reserved.")
    if len(value) < 2 or len(value) > 64:
        raise ValueError("Slug length must be between 2 and 64 chars.")
    return value


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ── Role membership (informational) ─────────────────────────────────────────


RoleKind = Literal["curator", "reviewer", "viewer"]


class RoleMember(BaseModel):
    """One row in a workspace's roles list — informational, not enforced."""

    email: str
    role: RoleKind


# ── Workspace ───────────────────────────────────────────────────────────────


class WorkspaceCreate(BaseModel):
    """Body for POST /v1/admin/workspaces."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str = Field(min_length=1, max_length=120)
    objective: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=2000)
    roles: list[RoleMember] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return _validate_slug(v)


class WorkspaceUpdate(BaseModel):
    """Body for PATCH /v1/admin/workspaces/{id}. All fields optional."""

    model_config = ConfigDict(extra="forbid")

    slug: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    objective: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    roles: list[RoleMember] | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        return _validate_slug(v) if v is not None else None


class Workspace(BaseModel):
    """Stored shape — also the response shape on every workspace endpoint."""

    id: str
    slug: str
    name: str
    objective: str = ""
    description: str = ""
    roles: list[RoleMember] = Field(default_factory=list)
    created_at: str
    created_by: str = ""
    updated_at: str
    updated_by: str = ""


# ── Business Domain ───────────────────────────────────────────────────────────
# (Formerly "Data Product". Renamed in the UX_CHANGES audit — see module
#  docstring. ``data_product_ids`` was ``entity_ids``.)


def _dedup_ids(v: list[str]) -> list[str]:
    # Preserve order but drop duplicates — the admin shouldn't have to think
    # about dedup when authoring.
    seen: set[str] = set()
    out: list[str] = []
    for eid in v:
        if eid and eid not in seen:
            seen.add(eid)
            out.append(eid)
    return out


class BusinessDomainCreate(BaseModel):
    """Body for POST /v1/admin/workspaces/{ws_id}/business-domains."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    data_product_ids: list[str] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return _validate_slug(v)

    @field_validator("data_product_ids")
    @classmethod
    def _dedup(cls, v: list[str]) -> list[str]:
        return _dedup_ids(v)


class BusinessDomainUpdate(BaseModel):
    """Body for PATCH /v1/admin/business-domains/{id}. All fields optional."""

    model_config = ConfigDict(extra="forbid")

    slug: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    data_product_ids: list[str] | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        return _validate_slug(v) if v is not None else None

    @field_validator("data_product_ids")
    @classmethod
    def _dedup(cls, v: list[str] | None) -> list[str] | None:
        return _dedup_ids(v) if v is not None else None


class DataProductRef(BaseModel):
    """Body for POST /v1/admin/business-domains/{id}/data-products.

    The incremental membership endpoints take a single entity id so the server
    can apply an atomic add/remove instead of the client replacing the whole
    ``data_product_ids`` array (which races under rapid "+" clicks)."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1)


class BusinessDomain(BaseModel):
    """Stored shape — also the response shape on every business-domain endpoint."""

    id: str
    workspace_id: str
    slug: str
    name: str
    description: str = ""
    data_product_ids: list[str] = Field(default_factory=list)
    created_at: str
    created_by: str = ""
    updated_at: str
    updated_by: str = ""


# ── Organization (singleton) ────────────────────────────────────────────────


class OrganizationUpdate(BaseModel):
    """Body for PUT /v1/admin/organization. Idempotent upsert."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(default="", max_length=200)
    # Generic source system (system + version), e.g. "SAP S/4HANA 2023",
    # "Salesforce", "PostgreSQL 15". Supersedes the SAP-specific ``sap_version``
    # (kept for back-compat reads). Feeds the per-entity source_system default
    # + the agent context. Design: ITERATION_ENTITY_CREATION_REDESIGN.md §3.3.
    source_system: str = Field(default="", max_length=200)
    sap_version: str = Field(default="", max_length=200)  # deprecated alias of source_system
    # Module codes the customer runs (SD, MM, PP, FI, CO, ...). Stored as
    # uppercase strings; the UI lets the admin pick from a chip selector.
    core_bases: list[str] = Field(default_factory=list)
    url: str = Field(default="", max_length=500)


class Organization(BaseModel):
    """Stored shape. ``id`` is always ``"default"`` (singleton)."""

    id: str = "default"
    company_name: str = ""
    source_system: str = ""
    sap_version: str = ""  # deprecated; read as fallback when source_system is empty
    core_bases: list[str] = Field(default_factory=list)
    url: str = ""
    updated_at: str = ""
    updated_by: str = ""


# ── Helpers for service / repo construction ─────────────────────────────────


def now_iso() -> str:
    """Single source of truth for timestamps so tests can monkeypatch one place."""
    return _utc_now_iso()


__all__ = [
    "BusinessDomain",
    "BusinessDomainCreate",
    "BusinessDomainUpdate",
    "DataProductRef",
    "Organization",
    "OrganizationUpdate",
    "RoleKind",
    "RoleMember",
    "Workspace",
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "now_iso",
]
