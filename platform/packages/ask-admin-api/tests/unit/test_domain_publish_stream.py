# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Router tests for POST /v1/admin/business-domains/{id}/publish/{env}/stream.

The streaming bulk publish emits one NDJSON event per Data Product so the SPA
can show live per-DP progress. These tests mock the workspace / lifecycle /
publish services (no OpenSearch, no git) and assert the event sequence + the
checklist subset selection.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ask_admin_api.models.data_products import DataProductLifecycle, PublishRecord


def _rec(sha: str, version: int = 1) -> PublishRecord:
    return PublishRecord(version=version, sha=sha, at="2026-06-26T00:00:00Z", by="t@x.com")


def _lc(entity_id: str, main_sha: str, dev=None, prod=None) -> DataProductLifecycle:
    return DataProductLifecycle(
        entity_id=entity_id, main_sha=main_sha, dev_published=dev, prod_published=prod
    )


class _FakeWorkspaceService:
    def __init__(self, bd) -> None:
        self._bd = bd

    def get_business_domain(self, bd_id: str):
        from ask_admin_api.application.workspace_service import BusinessDomainNotFoundError

        if bd_id != self._bd.id:
            raise BusinessDomainNotFoundError(bd_id)
        return self._bd


class _FakeLifecycle:
    def __init__(self, table: dict[str, DataProductLifecycle]) -> None:
        self._table = table

    def get(self, dp_id: str):
        return self._table.get(dp_id)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    from ask_admin_api.routers import business_domains

    # Domain with three members: a (never published), b (edited since dev),
    # c (already up to date with working) → for dev: a,b eligible, c skipped.
    bd = SimpleNamespace(id="bd1", name="Sales", data_product_ids=["a", "b", "c"])
    lifecycle = _FakeLifecycle(
        {
            "a": _lc("a", "m1"),  # dev_published None → eligible
            "b": _lc("b", "m2", dev=_rec("OLD")),  # sha mismatch → eligible
            "c": _lc("c", "m3", dev=_rec("m3")),  # up to date → skipped
        }
    )
    published_calls: list[tuple[str, str]] = []

    class _FakePublisher:
        def __init__(self, **_kw) -> None:
            pass

        def publish(self, entity_id: str, env: str, *, by: str):
            published_calls.append((entity_id, env))
            return SimpleNamespace(committed_sha=f"sha-{entity_id}")

    business_domains._svc = _FakeWorkspaceService(bd)
    business_domains._lifecycle = lifecycle
    monkeypatch.setattr(business_domains, "PublishService", _FakePublisher)

    from ask_admin_api.main import app

    yield TestClient(app), published_calls

    business_domains._svc = None
    business_domains._lifecycle = None
    get_settings.cache_clear()


def _events(resp) -> list[dict]:
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_stream_publishes_eligible_and_skips_uptodate(client):
    cli, calls = client
    resp = cli.post("/v1/admin/business-domains/bd1/publish/dev/stream", json={})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")

    events = _events(resp)
    start = events[0]
    done = events[-1]
    assert start["type"] == "start"
    assert start["total"] == 3
    assert start["planned"] == ["a", "b", "c"]

    # Every DP gets a processing + item event.
    items = {e["entity_id"]: e for e in events if e["type"] == "item"}
    assert items["a"]["outcome"] == "published"
    assert items["a"]["committed_sha"] == "sha-a"
    assert items["b"]["outcome"] == "published"
    assert items["c"]["outcome"] == "skipped"
    assert "up to date" in (items["c"]["reason"] or "")

    assert done["type"] == "done"
    assert (done["published"], done["skipped"], done["failed"]) == (2, 1, 0)
    # c was never sent to the publisher (gate short-circuits before publish).
    assert calls == [("a", "dev"), ("b", "dev")]


def test_stream_respects_entity_ids_subset(client):
    cli, calls = client
    resp = cli.post(
        "/v1/admin/business-domains/bd1/publish/dev/stream",
        json={"entity_ids": ["b"]},
    )
    assert resp.status_code == 200
    events = _events(resp)
    assert events[0]["planned"] == ["b"]
    done = events[-1]
    assert (done["total"], done["published"]) == (1, 1)
    assert calls == [("b", "dev")]


def test_stream_ignores_ids_not_in_domain(client):
    cli, calls = client
    resp = cli.post(
        "/v1/admin/business-domains/bd1/publish/dev/stream",
        json={"entity_ids": ["zzz", "a"]},  # zzz is not a member → dropped
    )
    assert resp.status_code == 200
    events = _events(resp)
    assert events[0]["planned"] == ["a"]  # order preserved from the domain, zzz gone
    assert calls == [("a", "dev")]


def test_stream_records_per_dp_error_without_aborting_batch(client, monkeypatch):
    cli, _calls = client
    from ask_admin_api.routers import business_domains

    class _BoomOnB:
        def __init__(self, **_kw) -> None:
            pass

        def publish(self, entity_id: str, env: str, *, by: str):
            if entity_id == "b":
                raise RuntimeError("git exploded")
            return SimpleNamespace(committed_sha=f"sha-{entity_id}")

    monkeypatch.setattr(business_domains, "PublishService", _BoomOnB)

    resp = cli.post("/v1/admin/business-domains/bd1/publish/dev/stream", json={})
    assert resp.status_code == 200
    events = _events(resp)
    items = {e["entity_id"]: e for e in events if e["type"] == "item"}
    assert items["a"]["outcome"] == "published"
    assert items["b"]["outcome"] == "error"
    assert "git exploded" in (items["b"]["reason"] or "")
    # The batch continued past b's failure to evaluate c.
    assert items["c"]["outcome"] == "skipped"
    done = events[-1]
    assert (done["published"], done["skipped"], done["failed"]) == (1, 1, 1)


def test_stream_unknown_env_is_400(client):
    cli, _calls = client
    resp = cli.post("/v1/admin/business-domains/bd1/publish/staging/stream", json={})
    assert resp.status_code == 400


def test_stream_unknown_domain_is_404(client):
    cli, _calls = client
    resp = cli.post("/v1/admin/business-domains/nope/publish/dev/stream", json={})
    assert resp.status_code == 404
