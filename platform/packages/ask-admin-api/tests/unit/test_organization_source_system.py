# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Organization ``source_system`` (generic) supersedes ``sap_version`` with a
back-compat fallback. Tests the service doc-building with a fake repo (no OpenSearch).
"""

from __future__ import annotations

from ask_admin_api.application.workspace_service import WorkspaceService
from ask_admin_api.models.workspaces import Organization, OrganizationUpdate


class _FakeRepo:
    def __init__(self) -> None:
        self.doc: dict | None = None

    def upsert_organization(self, doc: dict) -> Organization:
        self.doc = doc
        return Organization(**doc)

    def get_organization(self) -> Organization:
        return Organization(source_system="SAP S/4HANA 2023")


def test_upsert_prefers_source_system_and_mirrors_to_sap_version():
    repo = _FakeRepo()
    out = WorkspaceService(repo).upsert_organization(
        OrganizationUpdate(source_system="SAP S/4HANA 2023"), author_email="a@b.com"
    )
    assert repo.doc["source_system"] == "SAP S/4HANA 2023"
    assert repo.doc["sap_version"] == "SAP S/4HANA 2023"  # mirrored for old readers
    assert out.source_system == "SAP S/4HANA 2023"


def test_upsert_falls_back_to_legacy_sap_version():
    repo = _FakeRepo()
    WorkspaceService(repo).upsert_organization(
        OrganizationUpdate(sap_version="ECC 6.0"), author_email="a@b.com"
    )
    assert repo.doc["source_system"] == "ECC 6.0"
    assert repo.doc["sap_version"] == "ECC 6.0"


def test_update_model_accepts_source_system():
    body = OrganizationUpdate(source_system="Salesforce")
    assert body.source_system == "Salesforce"
