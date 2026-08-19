# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for workspace_scope_resolver — pure-Python (no OpenSearch, no LLM)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def _write_yaml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def yaml_service(tmp_path: Path):
    """Build a YAMLFileService against a workspace with a small mixed catalogue.

    The graph:
        gold_sales_perf  → (relationship)        → silver_invoice
        silver_invoice   → (composed_of)         → VBRK, VBRP  (= bronze ids)
        silver_invoice   → (relationship)        → silver_customer

    silver_unrelated has no inbound references — it must stay OUT of the scope.
    """
    repo_root = tmp_path
    workspace = repo_root / "workspace"
    _write_yaml(
        workspace / "bronze" / "vbrk.yaml",
        "id: bronze_vbrk\nlayer: bronze\nname: VBRK\n",
    )
    _write_yaml(
        workspace / "bronze" / "vbrp.yaml",
        "id: bronze_vbrp\nlayer: bronze\nname: VBRP\n",
    )
    _write_yaml(
        workspace / "bronze" / "kna1.yaml",
        "id: bronze_kna1\nlayer: bronze\nname: KNA1\n",
    )
    _write_yaml(
        workspace / "silver" / "sd" / "invoice.yaml",
        (
            "id: silver_invoice\n"
            "layer: silver\n"
            "name: invoice\n"
            "composed_of: [VBRK, VBRP]\n"
            "relationships:\n"
            "  - target_entity: silver_customer\n"
            "    relationship_type: many_to_one\n"
        ),
    )
    _write_yaml(
        workspace / "silver" / "sd" / "customer.yaml",
        ("id: silver_customer\nlayer: silver\nname: customer\ncomposed_of: [KNA1]\n"),
    )
    _write_yaml(
        workspace / "gold" / "sd" / "sales_perf.yaml",
        (
            "id: gold_sales_perf\n"
            "layer: gold\n"
            "name: sales_perf\n"
            "relationships:\n"
            "  - target_entity: silver_invoice\n"
            "    relationship_type: many_to_one\n"
        ),
    )
    _write_yaml(
        workspace / "silver" / "sd" / "unrelated.yaml",
        "id: silver_unrelated\nlayer: silver\nname: unrelated\n",
    )

    from ask_admin_api.application.yaml_file_service import YAMLFileService

    return YAMLFileService(workspace_path=str(workspace), repo_root=str(repo_root))


# ── Stub workspace + DP for the resolver ────────────────────────────────────


class _StubBD:
    def __init__(self, data_product_ids: list[str], bd_id: str = "bd-1") -> None:
        self.id = bd_id
        self.data_product_ids = data_product_ids


class _StubWorkspace:
    def __init__(self, ws_id: str = "ws-1") -> None:
        self.id = ws_id
        self.slug = ws_id


class _StubWorkspaceService:
    """Drop-in replacement for WorkspaceService — no OpenSearch."""

    def __init__(
        self,
        *,
        workspaces: dict[str, Any],
        dps_by_ws: dict[str, list[_StubBD]],
        bds_by_id: dict[str, _StubBD] | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._dps = dps_by_ws
        self._bds_by_id = bds_by_id or {}

    def get_workspace(self, id_or_slug: str):
        ws = self._workspaces.get(id_or_slug)
        if ws is None:
            from ask_admin_api.application.workspace_service import WorkspaceNotFoundError

            raise WorkspaceNotFoundError(id_or_slug)
        return ws

    def list_business_domains(self, ws_id: str) -> list[_StubBD]:
        return self._dps.get(ws_id, [])

    def get_business_domain(self, bd_id: str) -> _StubBD:
        bd = self._bds_by_id.get(bd_id)
        if bd is None:
            from ask_admin_api.application.workspace_service import BusinessDomainNotFoundError

            raise BusinessDomainNotFoundError(bd_id)
        return bd


# ── Tests ───────────────────────────────────────────────────────────────────


def test_expansion_includes_composed_of_and_relationship_targets(yaml_service):
    from ask_admin_api.application.workspace_scope_resolver import resolve_workspace_scope

    svc = _StubWorkspaceService(
        workspaces={"ws-1": _StubWorkspace("ws-1")},
        dps_by_ws={"ws-1": [_StubBD(data_product_ids=["silver_invoice"])]},
    )
    scope = resolve_workspace_scope("ws-1", yaml_service, workspace_service=svc)
    # Core + composed_of bronzes + 1-hop relationship target
    assert scope == {"silver_invoice", "bronze_vbrk", "bronze_vbrp", "silver_customer"}
    # Unrelated entity must not leak in.
    assert "silver_unrelated" not in scope


def test_expansion_from_gold_pulls_in_one_hop_silver(yaml_service):
    """A DP containing a gold should pull in the silvers it relates to."""
    from ask_admin_api.application.workspace_scope_resolver import resolve_workspace_scope

    svc = _StubWorkspaceService(
        workspaces={"ws-1": _StubWorkspace("ws-1")},
        dps_by_ws={"ws-1": [_StubBD(data_product_ids=["gold_sales_perf"])]},
    )
    scope = resolve_workspace_scope("ws-1", yaml_service, workspace_service=svc)
    # Gold + one-hop silver (no recursive transitive — invoice's neighbors stay out)
    assert "gold_sales_perf" in scope
    assert "silver_invoice" in scope
    # Transitive (silver_invoice → bronze_vbrk) is NOT expected because we go
    # only one hop from EACH core entity, not from expanded entities.
    assert "bronze_vbrk" not in scope


def test_empty_dp_returns_empty_set(yaml_service):
    from ask_admin_api.application.workspace_scope_resolver import resolve_workspace_scope

    svc = _StubWorkspaceService(
        workspaces={"ws-1": _StubWorkspace("ws-1")},
        dps_by_ws={"ws-1": [_StubBD(data_product_ids=[])]},
    )
    assert resolve_workspace_scope("ws-1", yaml_service, workspace_service=svc) == set()


def test_unknown_workspace_raises_scope_error(yaml_service):
    from ask_admin_api.application.workspace_scope_resolver import (
        WorkspaceScopeError,
        resolve_workspace_scope,
    )

    svc = _StubWorkspaceService(workspaces={}, dps_by_ws={})
    with pytest.raises(WorkspaceScopeError, match="ghost-ws"):
        resolve_workspace_scope("ghost-ws", yaml_service, workspace_service=svc)


def test_dp_referencing_missing_entity_is_skipped_silently(yaml_service):
    """Orphan entity_id (referenced by DP but missing on disk) doesn't crash."""
    from ask_admin_api.application.workspace_scope_resolver import resolve_workspace_scope

    svc = _StubWorkspaceService(
        workspaces={"ws-1": _StubWorkspace("ws-1")},
        dps_by_ws={
            "ws-1": [
                _StubBD(data_product_ids=["silver_invoice", "ghost_entity_that_doesnt_exist"]),
            ]
        },
    )
    scope = resolve_workspace_scope("ws-1", yaml_service, workspace_service=svc)
    # Real entity expansion still works; ghost is silently dropped.
    assert "silver_invoice" in scope
    assert "bronze_vbrk" in scope
    assert (
        "ghost_entity_that_doesnt_exist" in scope or "ghost_entity_that_doesnt_exist" not in scope
    )
    # Stricter: core remains in the set (we add it before checking disk).
    assert "ghost_entity_that_doesnt_exist" in scope


def test_composed_of_uses_case_insensitive_bronze_name_match(yaml_service, tmp_path):
    """SAP table names in composed_of can be in any case — match against the bronze.name uppercased."""
    from ask_admin_api.application.workspace_scope_resolver import resolve_workspace_scope

    # Re-write the silver_invoice with lowercase composed_of names.
    workspace = tmp_path / "workspace"
    _write_yaml(
        workspace / "silver" / "sd" / "invoice.yaml",
        ("id: silver_invoice\nlayer: silver\nname: invoice\ncomposed_of: [vbrk, vbrp]\n"),
    )
    svc = _StubWorkspaceService(
        workspaces={"ws-1": _StubWorkspace("ws-1")},
        dps_by_ws={"ws-1": [_StubBD(data_product_ids=["silver_invoice"])]},
    )
    scope = resolve_workspace_scope("ws-1", yaml_service, workspace_service=svc)
    assert "bronze_vbrk" in scope
    assert "bronze_vbrp" in scope


def test_composed_of_resolves_bronze_ids_directly(yaml_service, tmp_path):
    """composed_of carrying bronze ENTITY IDS (the form curated/ingested YAMLs
    actually use) must resolve, not just legacy SAP table names. Regression:
    id-form refs were dropped from scope, so a Silver's bronzes vanished from the
    domain canvas on refresh even though the drop showed them client-side."""
    from ask_admin_api.application.workspace_scope_resolver import resolve_domain_scope

    # Re-write the silver_invoice referencing its bronzes by id, not by name.
    workspace = tmp_path / "workspace"
    _write_yaml(
        workspace / "silver" / "sd" / "invoice.yaml",
        (
            "id: silver_invoice\nlayer: silver\nname: invoice\n"
            "composed_of: [bronze_vbrk, bronze_vbrp]\n"
        ),
    )
    bd = _StubBD(data_product_ids=["silver_invoice"], bd_id="bd-1")
    svc = _StubWorkspaceService(workspaces={}, dps_by_ws={}, bds_by_id={"bd-1": bd})
    scope = resolve_domain_scope("bd-1", yaml_service, workspace_service=svc)
    assert scope == {"silver_invoice", "bronze_vbrk", "bronze_vbrp"}


# ── Domain scope (design-spec §03 domain canvas) ──────────────────────────────


def test_domain_scope_is_strict_membership_plus_bronzes(yaml_service):
    """Domain scope = members + their composed_of bronzes ONLY — relationship
    targets are EXCLUDED (design-spec §03 strict membership). Contrast with the
    workspace test above, which keeps the one-hop relationship expansion."""
    from ask_admin_api.application.workspace_scope_resolver import resolve_domain_scope

    bd = _StubBD(data_product_ids=["silver_invoice"], bd_id="bd-1")
    svc = _StubWorkspaceService(workspaces={}, dps_by_ws={}, bds_by_id={"bd-1": bd})
    scope = resolve_domain_scope("bd-1", yaml_service, workspace_service=svc)
    # Member + its composed_of bronzes — but NOT the relationship target.
    assert scope == {"silver_invoice", "bronze_vbrk", "bronze_vbrp"}
    assert "silver_customer" not in scope  # relationship target, not a member
    assert "silver_unrelated" not in scope


def test_domain_scope_drops_removed_member_even_if_referenced(yaml_service):
    """obs5: removing a member that is still a relationship target of another
    member drops it from the canvas (strict membership ignores the dangling
    relation — it does NOT re-pull the removed entity back in)."""
    from ask_admin_api.application.workspace_scope_resolver import resolve_domain_scope

    # Before: both invoice and customer are members.
    before = _StubBD(data_product_ids=["silver_invoice", "silver_customer"], bd_id="bd-x")
    svc = _StubWorkspaceService(workspaces={}, dps_by_ws={}, bds_by_id={"bd-x": before})
    assert "silver_customer" in resolve_domain_scope("bd-x", yaml_service, workspace_service=svc)

    # After removing customer from membership — invoice still relates to it.
    after = _StubBD(data_product_ids=["silver_invoice"], bd_id="bd-x")
    svc2 = _StubWorkspaceService(workspaces={}, dps_by_ws={}, bds_by_id={"bd-x": after})
    scope = resolve_domain_scope("bd-x", yaml_service, workspace_service=svc2)
    assert "silver_customer" not in scope  # gone, despite being invoice's relationship target
    assert "silver_invoice" in scope
    assert "bronze_vbrk" in scope  # composed_of bronze still rendered


def test_domain_scope_empty_bd_returns_empty(yaml_service):
    from ask_admin_api.application.workspace_scope_resolver import resolve_domain_scope

    bd = _StubBD(data_product_ids=[], bd_id="bd-empty")
    svc = _StubWorkspaceService(workspaces={}, dps_by_ws={}, bds_by_id={"bd-empty": bd})
    assert resolve_domain_scope("bd-empty", yaml_service, workspace_service=svc) == set()


def test_domain_scope_unknown_bd_raises_scope_error(yaml_service):
    from ask_admin_api.application.workspace_scope_resolver import (
        WorkspaceScopeError,
        resolve_domain_scope,
    )

    svc = _StubWorkspaceService(workspaces={}, dps_by_ws={}, bds_by_id={})
    with pytest.raises(WorkspaceScopeError, match="ghost-bd"):
        resolve_domain_scope("ghost-bd", yaml_service, workspace_service=svc)
