# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Incremental Business-Domain membership (atomic add/remove of one entity).

Regression guard for the lost-update bug: the canvas "+"/drag used to PATCH the
whole ``data_product_ids`` array from a stale React closure, so a burst of rapid
adds each wrote ``base + {one}`` and the last writer won — most adds vanished on
reload. The service now delegates to the repo's *atomic* add/remove (a single
OpenSearch scripted update; concurrent adds are commutative) instead of a
client-driven read-modify-write. These tests pin that contract at the service
layer with a fake repo that models the atomic add-if-absent / removeIf semantics.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ask_admin_api.application.workspace_service import (
    BusinessDomainNotFoundError,
    WorkspaceService,
)


def _bd(bd_id: str, dps: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=bd_id,
        workspace_id="ws-1",
        slug=f"slug-{bd_id}",
        name=f"BD {bd_id}",
        description="",
        data_product_ids=list(dps),
        created_at="t0",
        created_by="u",
        updated_at="t0",
        updated_by="u",
    )


def _clone(bd: SimpleNamespace) -> SimpleNamespace:
    """Mirror the repo's realtime GET: a fresh doc (callers must not share the
    store's list) that reflects the just-applied stamps."""
    fresh = _bd(bd.id, bd.data_product_ids)
    fresh.updated_at, fresh.updated_by = bd.updated_at, bd.updated_by
    return fresh


class _FakeMembershipRepo:
    """Models the atomic scripted-update semantics: add-if-absent / removeIf."""

    def __init__(self, bds: list[SimpleNamespace]) -> None:
        self._bds = {bd.id: bd for bd in bds}

    def add_data_product(self, bd_id, entity_id, *, now, updated_by):
        bd = self._bds.get(bd_id)
        if bd is None:
            return None
        if entity_id not in bd.data_product_ids:  # add-if-absent (idempotent)
            bd.data_product_ids.append(entity_id)
        bd.updated_at, bd.updated_by = now, updated_by
        return _clone(bd)

    def remove_data_product(self, bd_id, entity_id, *, now, updated_by):
        bd = self._bds.get(bd_id)
        if bd is None:
            return None
        bd.data_product_ids = [x for x in bd.data_product_ids if x != entity_id]
        bd.updated_at, bd.updated_by = now, updated_by
        return _clone(bd)


def test_sequential_adds_accumulate_no_lost_update():
    repo = _FakeMembershipRepo([_bd("a", [])])
    svc = WorkspaceService(repo)
    for eid in ("silver_x", "silver_y", "silver_z"):
        svc.add_data_product("a", eid, author_email="curator@x.com")
    # All three survive — the old full-array replace from a stale base lost all
    # but the last writer here.
    assert repo._bds["a"].data_product_ids == ["silver_x", "silver_y", "silver_z"]


def test_add_is_idempotent():
    repo = _FakeMembershipRepo([_bd("a", ["silver_x"])])
    bd = WorkspaceService(repo).add_data_product("a", "silver_x", author_email="u@x.com")
    assert bd.data_product_ids == ["silver_x"]  # no duplicate


def test_add_stamps_author_and_returns_fresh_doc():
    repo = _FakeMembershipRepo([_bd("a", [])])
    bd = WorkspaceService(repo).add_data_product("a", "silver_x", author_email="curator@x.com")
    assert bd.updated_by == "curator@x.com"
    assert bd.updated_at != "t0"


def test_add_missing_domain_raises():
    svc = WorkspaceService(_FakeMembershipRepo([]))
    with pytest.raises(BusinessDomainNotFoundError):
        svc.add_data_product("ghost", "silver_x", author_email="u@x.com")


def test_remove_drops_only_target_and_is_idempotent():
    repo = _FakeMembershipRepo([_bd("a", ["silver_x", "silver_y"])])
    svc = WorkspaceService(repo)
    svc.remove_data_product("a", "silver_x", author_email="u@x.com")
    assert repo._bds["a"].data_product_ids == ["silver_y"]
    # removing a non-member is a no-op (idempotent)
    bd = svc.remove_data_product("a", "silver_x", author_email="u@x.com")
    assert bd.data_product_ids == ["silver_y"]


def test_remove_missing_domain_raises():
    svc = WorkspaceService(_FakeMembershipRepo([]))
    with pytest.raises(BusinessDomainNotFoundError):
        svc.remove_data_product("ghost", "silver_x", author_email="u@x.com")
