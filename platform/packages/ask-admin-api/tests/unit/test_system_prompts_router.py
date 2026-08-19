# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Smoke tests for ``/v1/admin/prompts/*`` — read default, write override, reset."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

_TEST_KEY = Fernet.generate_key().decode()


class _FakeOS:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict] = {}
        self.indices_state: set[str] = set()
        self.indices = _FakeIndicesClient(self)

    def get(self, *, index: str, id: str):  # noqa: A002
        key = (index, id)
        if key not in self.docs:
            from opensearchpy.exceptions import NotFoundError

            raise NotFoundError(404, "not_found", "doc not found")
        return {"_source": self.docs[key]}

    def index(self, *, index: str, id: str, body, refresh=None):  # noqa: A002
        self.docs[(index, id)] = dict(body)
        return {"result": "created"}

    def delete(self, *, index: str, id: str, refresh=None):  # noqa: A002
        self.docs.pop((index, id), None)
        return {"result": "deleted"}


class _FakeIndicesClient:
    def __init__(self, parent: _FakeOS) -> None:
        self._parent = parent

    def exists(self, *, index: str) -> bool:
        return index in self._parent.indices_state

    def create(self, *, index: str, body) -> dict:  # noqa: ARG002
        self._parent.indices_state.add(index)
        return {"acknowledged": True}


@pytest.fixture
def prompts_client(monkeypatch) -> TestClient:
    from ask_llm_gateway.infrastructure.secrets import crypto

    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, _TEST_KEY)
    crypto.reset_cache_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    # Wire the fake OS client into both secrets + prompts repos.
    from ask_admin_api.application import system_prompts_repository
    from ask_admin_api.routers import system_prompts as router_module
    from ask_llm_gateway.infrastructure.secrets import provider
    from ask_llm_gateway.infrastructure.secrets import repository as secrets_repo

    fake = _FakeOS()
    monkeypatch.setattr(system_prompts_repository, "_build_client", lambda: fake)
    monkeypatch.setattr(secrets_repo, "_build_client", lambda: fake)
    provider.set_secrets_provider_for_tests(None)
    router_module._SERVICE = None

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    from ask_admin_api.main import app

    with TestClient(app) as client:
        yield client


def test_get_enrichment_returns_default_body(prompts_client: TestClient):
    resp = prompts_client.get("/v1/admin/prompts/enrichment")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key"] == "enrichment"
    assert body["is_default"] is True
    assert "SAP" in body["body"], "default body should contain the role definition"
    assert "WHAT YOU MUST NEVER TOUCH" in body["body"]
    # The output format must instruct strict JSON now, not full-YAML round-trip.
    assert "OUTPUT FORMAT" in body["body"]
    assert "JSON" in body["body"]


def test_put_then_get_persists_override(prompts_client: TestClient):
    new_body = "Custom enrichment prompt body for testing"
    put_resp = prompts_client.put("/v1/admin/prompts/enrichment", json={"body": new_body})
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json()["body"] == new_body
    assert put_resp.json()["is_default"] is False

    get_resp = prompts_client.get("/v1/admin/prompts/enrichment")
    assert get_resp.json()["body"] == new_body
    assert get_resp.json()["is_default"] is False


def test_put_empty_body_resets_to_default(prompts_client: TestClient):
    prompts_client.put("/v1/admin/prompts/enrichment", json={"body": "override"}).raise_for_status()
    reset_resp = prompts_client.put("/v1/admin/prompts/enrichment", json={"body": ""})
    assert reset_resp.status_code == 200
    assert reset_resp.json()["is_default"] is True
    # Default body comes back — keyed on the rule-of-thumb the new default
    # leads with. (The previous "RETRIEVAL OPTIMIZATION" header is gone in
    # the 2026-06 rewrite.)
    assert "signal, not filler" in reset_resp.json()["body"]


def test_unknown_key_returns_404(prompts_client: TestClient):
    resp = prompts_client.get("/v1/admin/prompts/not_a_real_key")
    assert resp.status_code == 404


def test_standards_excerpt_present_in_response(prompts_client: TestClient):
    """If the standards doc exists in the repo, the GET response should ship its excerpt."""
    resp = prompts_client.get("/v1/admin/prompts/enrichment")
    body = resp.json()
    # The excerpt can be empty if the doc moved, but key must be present.
    assert "standards_excerpt" in body
