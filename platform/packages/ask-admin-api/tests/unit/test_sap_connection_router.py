# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The SAP connection router, now that the section lives in the encrypted store.

The test that matters most is the partial-update merge. ``SecretsRepository``
``upsert`` REPLACES the whole document and only carries SENSITIVE fields
forward, so a screen that saves half the section would delete the other half.
Two screens do exactly that: the SAP form owns host / odata_path / username /
password, and the MCP page owns mcp_url / port.

The failure that guards against is invisible: nothing reports a missing
``mcp_url``, chat just quietly loses action execution
(``ask_action_execution.application.factory._build_adapter`` returns None).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ask_admin_api.routers import sap_connection


class _FakeRepo:
    """Stands in for SecretsRepository with the same replace-not-merge contract."""

    def __init__(self) -> None:
        self.doc: dict[str, Any] = {}
        self.upserts: list[dict[str, Any]] = []

    def upsert(
        self,
        target: str,
        *,
        provider: str,
        model: str,
        fields: dict[str, str],
        updated_by: str,
        preserve_blank_secrets: bool = False,
    ) -> dict[str, Any]:
        self.upserts.append(dict(fields))
        kept = dict(self.doc)
        # Mirror the real thing: everything is replaced, except that a blank
        # sensitive field keeps its stored value when preserve_blank_secrets.
        new = {k: v for k, v in fields.items() if v != ""}
        if preserve_blank_secrets and not fields.get("password") and kept.get("password"):
            new["password"] = kept["password"]
        self.doc = new
        return self.doc


@pytest.fixture
def sap_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _FakeRepo]:
    repo = _FakeRepo()

    monkeypatch.setattr(sap_connection, "_repo", lambda: repo)
    monkeypatch.setattr(sap_connection, "resolve_sap_config", lambda: dict(repo.doc))

    class _Provider:
        def invalidate(self, target: str | None = None) -> None:
            return None

    monkeypatch.setattr(sap_connection, "get_secrets_provider", lambda: _Provider())
    # Saving the section fires an MCP restart as a side effect. Stub the whole
    # call, not `threading.Thread`: the thread is an implementation detail of
    # `application.container_control`, and patching it here used to couple this
    # test to that choice. What this file asserts is the merge, not the restart.
    monkeypatch.setattr(
        sap_connection, "restart_container_in_background", lambda *a, **kw: None
    )

    app = FastAPI()

    class _Claims:
        email = "tester@onibex.com"

    app.dependency_overrides[sap_connection.validate_token] = lambda: _Claims()
    app.include_router(sap_connection.router)
    return TestClient(app), repo


def test_saving_the_sap_form_does_not_wipe_the_mcp_url(
    sap_client: tuple[TestClient, _FakeRepo],
) -> None:
    """The regression this whole file exists for."""
    client, repo = sap_client
    repo.doc = {
        "host": "https://sap.example",
        "odata_path": "/sap/opu/odata/sap/SRV",
        "username": "olduser",
        "password": "s3cret",
        "mcp_url": "http://ask-mcp:4004",
        "port": 4004,
    }

    resp = client.put(
        "/v1/admin/sap-connection",
        json={"host": "https://sap2.example", "username": "newuser"},
    )

    assert resp.status_code == 200
    assert repo.doc["mcp_url"] == "http://ask-mcp:4004", "the MCP url was wiped"
    assert str(repo.doc["port"]) == "4004"
    assert repo.doc["host"] == "https://sap2.example"
    assert repo.doc["username"] == "newuser"
    assert repo.doc["odata_path"] == "/sap/opu/odata/sap/SRV", "odata_path was wiped"


def test_saving_the_mcp_page_does_not_wipe_the_sap_credentials(
    sap_client: tuple[TestClient, _FakeRepo],
) -> None:
    """The mirror image, which is what the Setup MCP page now sends."""
    client, repo = sap_client
    repo.doc = {
        "host": "https://sap.example",
        "odata_path": "/sap/opu/odata/sap/SRV",
        "username": "olduser",
        "password": "s3cret",
        "mcp_url": "http://old-mcp:4004",
        "port": 4004,
    }

    resp = client.put(
        "/v1/admin/sap-connection",
        json={"mcp_url": "http://new-mcp:5005/", "port": 5005},
    )

    assert resp.status_code == 200
    assert repo.doc["host"] == "https://sap.example", "the SAP host was wiped"
    assert repo.doc["username"] == "olduser"
    assert repo.doc["password"] == "s3cret", "the SAP password was wiped"
    assert repo.doc["mcp_url"] == "http://new-mcp:5005", "the trailing slash was kept"
    assert str(repo.doc["port"]) == "5005"


def test_the_mask_round_trips_without_clearing_the_password(
    sap_client: tuple[TestClient, _FakeRepo],
) -> None:
    """A client that echoes back what GET gave it must not wipe the password."""
    client, repo = sap_client
    repo.doc = {"host": "https://sap.example", "username": "u", "password": "s3cret"}

    masked = client.get("/v1/admin/sap-connection").json()["config"]
    assert masked["password"] == sap_connection._MASK
    assert masked["password"] != "s3cret", "the real password reached the client"

    resp = client.put(
        "/v1/admin/sap-connection",
        json={"host": "https://sap.example", "username": "u", "password": masked["password"]},
    )

    assert resp.status_code == 200
    assert repo.doc["password"] == "s3cret"
    # The mask must never be what gets stored.
    assert sap_connection._MASK not in repo.upserts[-1].values()


def test_get_masks_the_password_and_leaves_the_rest_alone(
    sap_client: tuple[TestClient, _FakeRepo],
) -> None:
    client, repo = sap_client
    repo.doc = {"host": "https://sap.example", "username": "u", "password": "s3cret", "port": 4004}

    config = client.get("/v1/admin/sap-connection").json()["config"]

    assert config["host"] == "https://sap.example"
    assert config["username"] == "u"
    assert config["port"] == 4004
    assert config["password"] == sap_connection._MASK


def test_test_endpoint_says_so_when_nothing_is_configured(
    sap_client: tuple[TestClient, _FakeRepo],
) -> None:
    """An empty store must not be reported as a connection failure."""
    client, _repo = sap_client

    body = client.post("/v1/admin/sap-connection/test").json()

    assert body["ok"] is False
    assert "not configured" in body["message"]
