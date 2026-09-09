# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The contracts router, now that the API contracts live in OpenSearch.

Two behaviours are pinned here because getting either wrong is invisible in
production:

1. **A save replaces, it does not merge.** The SAP move nearly shipped the
   opposite bug: ``SecretsRepository.upsert`` replaces the whole document while
   ``preserve_blank_secrets`` only carries sensitive fields forward, so a
   partial save deleted the plain fields it omitted. Contracts are the mirror
   case. One screen owns the whole document, so replace is correct, and the
   test below proves that deleting an entity set in the UI really deletes it
   rather than having it resurrected by a merge.

2. **The machine-to-machine read 404s when nothing is stored.** The MCP server
   must retry rather than boot with an empty contract set, which would expose
   zero tools while reporting healthy.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ask_admin_api.routers import contracts


class _FakeRepo:
    """Stands in for ContractsRepository, one stored document per env."""

    store: dict[str, dict[str, Any]] = {}
    built_with: list[str | None] = []

    def __init__(self, client: Any = None, env: str | None = None) -> None:
        self._env = env
        type(self).built_with.append(env)

    def get(self) -> dict[str, Any] | None:
        return type(self).store.get(self._env or "")

    def upsert(self, config: dict[str, Any], updated_by: str) -> dict[str, Any]:
        # The real repository indexes the document by a constant id, so the
        # stored value is replaced outright. Mirror exactly that.
        type(self).store[self._env or ""] = config
        return config


@pytest.fixture
def contracts_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _FakeRepo.store = {}
    _FakeRepo.built_with = []
    monkeypatch.setattr(contracts, "ContractsRepository", _FakeRepo)

    app = FastAPI()

    class _Claims:
        email = "tester@onibex.com"

    app.dependency_overrides[contracts.validate_token] = lambda: _Claims()
    app.dependency_overrides[contracts.verify_api_key] = lambda: {"principal": "ask-mcp"}
    app.include_router(contracts.router)
    app.include_router(contracts.internal_router)
    return TestClient(app)


# ── The admin routes keep their old shapes ────────────────────────────────────


def test_get_returns_the_empty_skeleton_when_nothing_is_stored(
    contracts_client: TestClient,
) -> None:
    """The Setup page needs something to render, exactly as the file reader did."""
    resp = contracts_client.get("/v1/admin/contracts")

    assert resp.status_code == 200
    assert resp.json() == {"config": {"server": {}, "apis": []}}


def test_get_returns_what_was_saved(contracts_client: TestClient) -> None:
    stored = {"server": {"name": "s4h"}, "apis": [{"name": "A_SalesOrder"}]}
    _FakeRepo.store["dev"] = stored

    resp = contracts_client.get("/v1/admin/contracts")

    assert resp.status_code == 200
    assert resp.json() == {"config": stored}


def test_post_saves_and_answers_with_the_old_shape(contracts_client: TestClient) -> None:
    config = {"server": {"name": "s4h"}, "apis": [{"name": "A_SalesOrder"}]}

    resp = contracts_client.post("/v1/admin/contracts", json={"config": config})

    assert resp.status_code == 200
    assert resp.json() == {"success": True, "message": "Contracts saved."}
    assert _FakeRepo.store["dev"] == config


# ── The write path: replace, never merge ──────────────────────────────────────


def test_saving_a_smaller_set_really_deletes_the_removed_entity_set(
    contracts_client: TestClient,
) -> None:
    """The partial-write question T4 asks, answered deliberately.

    An operator who removes an entity set on the Contracts page and saves must
    end up without it. A merge would resurrect it, and nothing on any screen
    would say so.
    """
    _FakeRepo.store["dev"] = {
        "server": {"name": "s4h"},
        "apis": [{"name": "A_SalesOrder"}, {"name": "A_BusinessPartner"}],
    }

    smaller = {"server": {"name": "s4h"}, "apis": [{"name": "A_SalesOrder"}]}
    resp = contracts_client.post("/v1/admin/contracts", json={"config": smaller})

    assert resp.status_code == 200
    stored = _FakeRepo.store["dev"]
    names = [api["name"] for api in stored["apis"]]
    assert names == ["A_SalesOrder"], "the removed entity set came back"
    assert stored == smaller


def test_saving_an_empty_set_is_allowed_and_is_not_the_same_as_unconfigured(
    contracts_client: TestClient,
) -> None:
    """An operator can deliberately store nothing, and that is a real answer."""
    resp = contracts_client.post(
        "/v1/admin/contracts", json={"config": {"server": {}, "apis": []}}
    )

    assert resp.status_code == 200
    assert "dev" in _FakeRepo.store, "an empty save must still store a document"

    machine = contracts_client.get("/v1/internal/api-contracts")
    assert machine.status_code == 200, "a stored empty set is a 200, not a 404"


# ── Environments ──────────────────────────────────────────────────────────────


def test_dev_and_prod_are_separate_documents(contracts_client: TestClient) -> None:
    dev_config = {"server": {}, "apis": [{"name": "DevOnly"}]}
    prod_config = {"server": {}, "apis": [{"name": "ProdOnly"}]}

    contracts_client.post("/v1/admin/contracts?env=dev", json={"config": dev_config})
    contracts_client.post("/v1/admin/contracts?env=prod", json={"config": prod_config})

    assert contracts_client.get("/v1/admin/contracts?env=dev").json()["config"] == dev_config
    assert contracts_client.get("/v1/admin/contracts?env=prod").json()["config"] == prod_config


def test_the_default_environment_is_dev(contracts_client: TestClient) -> None:
    """The Setup SPA sends no env, so it must keep landing where it always did."""
    contracts_client.get("/v1/admin/contracts")

    assert _FakeRepo.built_with == ["dev"]


def test_an_unknown_environment_is_a_400_not_a_silent_write_elsewhere(
    contracts_client: TestClient,
) -> None:
    resp = contracts_client.post(
        "/v1/admin/contracts?env=staging", json={"config": {"apis": []}}
    )

    assert resp.status_code == 400
    assert "staging" in resp.json()["detail"]
    assert _FakeRepo.store == {}, "a rejected env must not have written anything"


# ── The machine-to-machine read ───────────────────────────────────────────────


def test_the_machine_read_404s_when_nothing_is_stored(
    contracts_client: TestClient,
) -> None:
    """So the MCP server retries instead of booting with zero tools."""
    resp = contracts_client.get("/v1/internal/api-contracts")

    assert resp.status_code == 404
    assert "dev" in resp.json()["detail"]


def test_the_machine_read_returns_the_stored_config(
    contracts_client: TestClient,
) -> None:
    stored = {"server": {"name": "s4h"}, "apis": [{"name": "A_SalesOrder"}]}
    _FakeRepo.store["prod"] = stored

    resp = contracts_client.get("/v1/internal/api-contracts?env=prod")

    assert resp.status_code == 200
    assert resp.json() == {"config": stored}
