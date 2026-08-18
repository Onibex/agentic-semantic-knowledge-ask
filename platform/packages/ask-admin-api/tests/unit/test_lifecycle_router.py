# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for the lifecycle / catalog router enrichment.

The catalog read shape (``CatalogRow``) layers a *derived* ``pending_conflicts``
count on top of the stored lifecycle doc. A conflict is an orthogonal attribute,
not a status — these tests pin that the count is computed from the sidecars and
never invented as a new lifecycle state.
"""

from __future__ import annotations

from ask_admin_api.models.data_products import CatalogRow, new_lifecycle_doc
from ask_admin_api.routers.lifecycle import _pending_conflict_counts
from tests.unit.conftest import SILVER_ID, seed_silver_conflict


def test_pending_conflict_counts_groups_by_entity(viz_repo):
    """Maps yaml_id -> unresolved count from the sidecars; empty when nothing pending."""
    assert _pending_conflict_counts() == {}

    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    assert _pending_conflict_counts().get(SILVER_ID) == 1


def test_pending_conflict_counts_excludes_resolved(viz_repo):
    """Resolved conflicts are not counted — the attribute reflects only blocking drift."""
    seed_silver_conflict(viz_repo, conflict_id="conf-1", resolved=True)
    assert _pending_conflict_counts().get(SILVER_ID, 0) == 0


def test_catalog_row_is_lifecycle_plus_derived_count():
    """CatalogRow = stored lifecycle doc + a derived (default 0) pending_conflicts."""
    doc = new_lifecycle_doc("silver_x", main_sha="abc")
    row = CatalogRow(**doc.model_dump(), pending_conflicts=3)
    assert (row.entity_id, row.status, row.pending_conflicts) == ("silver_x", "In Review", 3)
    # Defaults to 0 so the field never has to be stored in the lifecycle index.
    assert CatalogRow(**doc.model_dump()).pending_conflicts == 0
