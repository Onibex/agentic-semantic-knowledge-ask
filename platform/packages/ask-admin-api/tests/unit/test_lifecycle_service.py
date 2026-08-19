# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for LifecycleService — pure-Python (fake in-memory repo).

Pins the subtle version/status semantics (UX_CHANGES audit §5.3):
  * version increments on the first edit AFTER a release, not at publish time.
  * status is Released iff main_sha == dev_published.sha.
"""

from __future__ import annotations

import pytest

from ask_admin_api.application import lifecycle_triggers
from ask_admin_api.application.lifecycle_service import (
    LifecycleService,
    PublishNotReadyError,
)
from ask_admin_api.models.data_products import DataProductLifecycle
from ask_admin_api.models.workspaces import BusinessDomain, now_iso


class _FakeRepo:
    """In-memory stand-in for LifecycleRepository — no OpenSearch."""

    def __init__(self) -> None:
        self.docs: dict[str, DataProductLifecycle] = {}

    def get(self, entity_id: str):
        doc = self.docs.get(entity_id)
        return doc.model_copy(deep=True) if doc else None

    def list_all(self):
        return [d.model_copy(deep=True) for d in self.docs.values()]

    def list_by_workspace(self, workspace_id: str):
        return [
            d.model_copy(deep=True) for d in self.docs.values() if d.workspace_id == workspace_id
        ]

    def upsert(self, doc: DataProductLifecycle):
        self.docs[doc.entity_id] = doc.model_copy(deep=True)
        return doc


@pytest.fixture
def svc() -> LifecycleService:
    return LifecycleService(repo=_FakeRepo())


def test_create_is_in_review_v1(svc):
    doc = svc.on_create("silver_x", workspace_id="ws-1")
    assert doc.status == "In Review"
    assert doc.version == 1
    assert doc.dev_published is None
    assert doc.prod_published is None


def test_publish_dev_releases_at_current_version(svc):
    svc.on_create("silver_x")
    doc = svc.on_publish_dev("silver_x", by="a@x.com")
    assert doc.status == "Released"
    assert doc.dev_published is not None
    assert doc.dev_published.version == 1
    assert doc.dev_published.sha == doc.main_sha  # sha == main_sha (audit §5.3)


def test_edit_after_release_bumps_version_and_unreleases(svc):
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")  # Released v1
    doc = svc.on_edit("silver_x")
    assert doc.status == "In Review"
    assert doc.version == 2  # draft v2, dev still v1
    assert doc.dev_published.version == 1


def test_second_edit_while_in_review_does_not_bump(svc):
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")
    svc.on_edit("silver_x")  # → v2 In Review
    doc = svc.on_edit("silver_x")  # still drafting
    assert doc.status == "In Review"
    assert doc.version == 2


def test_republish_dev_records_new_version(svc):
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")
    svc.on_edit("silver_x")
    doc = svc.on_publish_dev("silver_x", by="a@x.com")  # cut v2
    assert doc.status == "Released"
    assert doc.dev_published.version == 2


def test_publish_prod_promotes_dev_no_bump(svc):
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")
    doc = svc.on_publish_prod("silver_x", by="a@x.com")
    assert doc.status == "Released"
    assert doc.prod_published is not None
    assert doc.prod_published.version == 1
    assert doc.prod_published.sha == doc.dev_published.sha


def test_publish_prod_before_dev_raises(svc):
    svc.on_create("silver_x")
    with pytest.raises(PublishNotReadyError):
        svc.on_publish_prod("silver_x", by="a@x.com")


def test_unpublish_dev_clears_record_and_unreleases(svc):
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")  # Released, dev v1
    doc = svc.on_unpublish_dev("silver_x", by="a@x.com")
    assert doc.dev_published is None
    assert doc.status == "In Review"  # no dev record → not released


def test_unpublish_prod_clears_only_prod(svc):
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")
    svc.on_publish_prod("silver_x", by="a@x.com")
    doc = svc.on_unpublish_prod("silver_x", by="a@x.com")
    assert doc.prod_published is None
    assert doc.dev_published is not None  # dev untouched → still answerable in dev
    assert doc.status == "Released"  # status derives from dev


def test_unpublish_then_republish_roundtrip(svc):
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")
    svc.on_unpublish_dev("silver_x", by="a@x.com")
    doc = svc.on_publish_dev("silver_x", by="a@x.com")  # re-publish restores
    assert doc.dev_published is not None
    assert doc.status == "Released"


def test_unpublish_missing_record_raises(svc):
    with pytest.raises(PublishNotReadyError):
        svc.on_unpublish_dev("ghost", by="a@x.com")


def test_sap_merge_behaves_like_edit(svc):
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")
    doc = svc.on_sap_merge("silver_x")
    assert doc.status == "In Review"
    assert doc.version == 2


def test_recompute_membership_seeds_and_links(svc):
    bd = BusinessDomain(
        id="bd-1",
        workspace_id="ws-1",
        slug="order-to-cash",
        name="Order to Cash",
        data_product_ids=["silver_a", "silver_b"],
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    svc.recompute_membership({"silver_a", "silver_b"}, [bd])
    a = svc.get("silver_a")
    assert a is not None
    assert a.business_domain_ids == ["bd-1"]
    assert a.workspace_id == "ws-1"
    assert a.status == "In Review"  # seeded


def test_recompute_membership_drops_stale_links(svc):
    bd1 = BusinessDomain(
        id="bd-1",
        workspace_id="ws-1",
        slug="otc",
        name="OTC",
        data_product_ids=["silver_a"],
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    svc.recompute_membership({"silver_a"}, [bd1])
    # bd-1 no longer references silver_a → reverse index empties.
    bd1_empty = bd1.model_copy(update={"data_product_ids": []})
    svc.recompute_membership({"silver_a"}, [bd1_empty])
    a = svc.get("silver_a")
    assert a.business_domain_ids == []


# ── fire_on_merge: SAP-JSON merge lifecycle (catalog-visibility fix) ───────────
# Regression for the OneConnect bug: first-ingest entities (esp. Bronzes) must
# get a lifecycle doc so they show in the catalog — the merge handler used to
# fire only for the Silver. Tested at the trigger-helper level with the same
# in-memory _FakeRepo, monkeypatching the module singleton.


def _patch_triggers(monkeypatch) -> LifecycleService:
    svc = LifecycleService(repo=_FakeRepo())
    monkeypatch.setattr(lifecycle_triggers, "_svc", svc)
    return svc


def test_fire_on_merge_seeds_every_created_entity(monkeypatch):
    svc = _patch_triggers(monkeypatch)
    lifecycle_triggers.fire_on_merge(
        created_entities=["bronze_a", "bronze_b", "silver_x"],
        silver_id="silver_x",
        working_changed=True,
    )
    for eid in ("bronze_a", "bronze_b", "silver_x"):
        doc = svc.get(eid)
        assert doc is not None, f"{eid} should have a lifecycle doc (catalog visibility)"
        assert doc.status == "In Review"
        assert doc.version == 1  # first-ingest Silver is on_create, not a v-bump


def test_fire_on_merge_preexisting_silver_back_to_in_review(monkeypatch):
    svc = _patch_triggers(monkeypatch)
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")  # Released v1
    lifecycle_triggers.fire_on_merge(
        created_entities=["bronze_new"],
        silver_id="silver_x",
        working_changed=True,
    )
    assert svc.get("bronze_new").status == "In Review"  # newly seeded → visible
    silver = svc.get("silver_x")
    assert silver.status == "In Review" and silver.version == 2  # on_sap_merge fired


def test_fire_on_merge_no_op_when_nothing_changed(monkeypatch):
    svc = _patch_triggers(monkeypatch)
    svc.on_create("silver_x")
    svc.on_publish_dev("silver_x", by="a@x.com")  # Released v1
    # No new entities, working not changed (e.g. conflicts-only) → Silver stays put.
    lifecycle_triggers.fire_on_merge(
        created_entities=[],
        silver_id="silver_x",
        working_changed=False,
    )
    silver = svc.get("silver_x")
    assert silver.status == "Released" and silver.version == 1
