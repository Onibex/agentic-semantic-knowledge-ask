# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Saved chats and artifacts (``/v1/chats``, ``/v1/artifacts``).

What these pin
──────────────
The chat SPA kept both in ``localStorage``: invisible from any other browser,
and visible to the next user who signed in on the same one. Server-side, the
property that matters is that an item is its owner's alone: another user can
neither list, read, overwrite nor delete it, and an id that is someone else's
answers exactly like one that does not exist. The rows inside must also be
encrypted at rest, and the lists must not drag them along.
"""

from __future__ import annotations

import importlib.util
import itertools
import os
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet, MultiFernet
from fastapi.testclient import TestClient
from opensearchpy.exceptions import NotFoundError

from ask_llm_gateway.infrastructure.secrets import crypto
from ask_orchestrator import user_store
from ask_orchestrator.auth.validator import TokenClaims, validate_token
from ask_orchestrator.main import app
from ask_orchestrator.user_store import (
    ARTIFACTS,
    CHATS,
    UserStore,
    get_artifact_store,
    get_chat_store,
)

ALICE = TokenClaims(sub="u-alice", email="alice@onibex.com", roles=[], issuer="keycloak")
BOB = TokenClaims(sub="u-bob", email="bob@onibex.com", roles=[], issuer="keycloak")

# A figure that must never be readable in OpenSearch.
SECRET_FIGURE = "8,123,456.78"


class _FakeIndices:
    def __init__(self, owner: _FakeOpenSearch) -> None:
        self._owner = owner

    def exists(self, index: str) -> bool:
        return index in self._owner.docs

    def create(self, index: str, body: dict[str, Any]) -> None:
        self._owner.docs[index] = {}
        self._owner.mappings[index] = body

    def refresh(self, index: str) -> None:
        pass


class _FakeOpenSearch:
    """Just enough of opensearch-py for UserStore: get / index / delete by id,
    the owner-filtered search the lists run, and the partial update the key
    rotation script makes."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, dict[str, Any]]] = {}
        self.mappings: dict[str, dict[str, Any]] = {}
        self.indices = _FakeIndices(self)

    def _index(self, index: str) -> dict[str, dict[str, Any]]:
        if index not in self.docs:
            raise NotFoundError(404, "index_not_found_exception", {})
        return self.docs[index]

    def get(self, index: str, id: str) -> dict[str, Any]:  # noqa: A002 — mirrors opensearch-py
        docs = self._index(index)
        if id not in docs:
            raise NotFoundError(404, "not_found", {})
        return {"_id": id, "_source": dict(docs[id])}

    def index(self, index: str, id: str, body: dict[str, Any], refresh: str) -> None:  # noqa: A002
        self._index(index)[id] = dict(body)

    def delete(self, index: str, id: str, refresh: str) -> None:  # noqa: A002
        docs = self._index(index)
        if id not in docs:
            raise NotFoundError(404, "not_found", {})
        del docs[id]

    def update(self, index: str, id: str, body: dict[str, Any]) -> None:  # noqa: A002
        self._index(index)[id].update(body["doc"])

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        terms = [f["term"] for f in body["query"]["bool"]["filter"]]
        hits = [
            (doc_id, src)
            for doc_id, src in self._index(index).items()
            if all(src.get(k) == v for t in terms for k, v in t.items())
        ]
        hits.sort(key=lambda h: h[1]["created_at"], reverse=True)
        excluded = set(body["_source"]["excludes"])
        return {
            "hits": {
                "hits": [
                    {"_id": doc_id, "_source": {k: v for k, v in src.items() if k not in excluded}}
                    for doc_id, src in hits[: body["size"]]
                ]
            }
        }


@pytest.fixture
def os_client() -> _FakeOpenSearch:
    return _FakeOpenSearch()


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    monkeypatch.setenv("ONIBEX_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_cache_for_tests()
    yield
    crypto.reset_cache_for_tests()


@pytest.fixture(autouse=True)
def ordered_clock(monkeypatch):
    """Strictly increasing timestamps, so ordering never depends on two writes
    landing in different milliseconds."""
    ticks = itertools.count()
    monkeypatch.setattr(
        user_store, "_now", lambda: f"2026-10-26T10:00:{next(ticks):02d}.000+00:00"
    )


@pytest.fixture
def as_user(os_client):
    """``as_user(ALICE)`` gives a TestClient that calls as Alice."""
    current: dict[str, TokenClaims] = {}

    async def _claims() -> TokenClaims:
        return current["claims"]

    app.dependency_overrides[validate_token] = _claims
    app.dependency_overrides[get_chat_store] = lambda: UserStore(CHATS, client=os_client)
    app.dependency_overrides[get_artifact_store] = lambda: UserStore(ARTIFACTS, client=os_client)
    client = TestClient(app)

    def _as(claims: TokenClaims) -> TestClient:
        current["claims"] = claims
        return client

    yield _as
    app.dependency_overrides.clear()


def _chat(workspace_id: str = "ws-1", title: str = "Sales by plant") -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "title": title,
        "data": {
            "sessionId": "s-1",
            "messages": [
                {"id": "m-1", "role": "user", "text": "net sales by plant"},
                {
                    "id": "m-2",
                    "role": "assistant",
                    "text": f"Total: {SECRET_FIGURE}",
                    "meta": {"sql": "SELECT 1", "rows": [{"planta": "Monterrey", "venta": 8123456.78}]},
                },
            ],
        },
    }


def _artifact(name: str = "Q3 sales") -> dict[str, Any]:
    return {
        "workspace_id": "ws-1",
        "env": "prod",
        "name": name,
        "artifact_type": "custom",
        "format": "detailed_report",
        "data": {
            "content": f"# Q3\n\nNet sales **{SECRET_FIGURE}**",
            "datasets": [{"name": "Main Dataset", "sql": "SELECT 1", "rows": [{"venta": 8123456.78}]}],
            "_request": {"purpose": "review", "data_focus": "sales", "env": "prod", "mode": "smart"},
        },
    }


KINDS = [
    pytest.param("chats", _chat, id="chats"),
    pytest.param("artifacts", _artifact, id="artifacts"),
]


@pytest.mark.parametrize(("route", "make"), KINDS)
def test_an_item_is_its_owners_alone(as_user, os_client, route, make):
    """The leak this replaces, server-side: Bob can neither list, read,
    overwrite nor delete Alice's item, and gets the same 404 as for an id that
    does not exist."""
    assert as_user(ALICE).put(f"/v1/{route}/item-1", json=make()).status_code == 200

    bob = as_user(BOB)
    assert bob.get(f"/v1/{route}").json() == {"items": []}
    assert bob.get(f"/v1/{route}/item-1").status_code == 404
    assert bob.get(f"/v1/{route}/no-such-item").status_code == 404
    assert bob.put(f"/v1/{route}/item-1", json=make(**{"title" if route == "chats" else "name": "Bob's"})).status_code == 404
    if route == "chats":
        assert bob.delete("/v1/chats/item-1").status_code == 404

    alice = as_user(ALICE)
    (listed,) = alice.get(f"/v1/{route}").json()["items"]
    assert listed["id"] == "item-1"
    assert "Bob's" not in listed.values()
    assert alice.get(f"/v1/{route}/item-1").json()["data"] == make()["data"]


@pytest.mark.parametrize(("route", "make"), KINDS)
def test_the_same_user_gets_the_item_back_whole(as_user, route, make):
    """What Chrome saves, Edge reads: the data comes back exactly as sent."""
    as_user(ALICE).put(f"/v1/{route}/item-1", json=make())

    got = as_user(ALICE).get(f"/v1/{route}/item-1").json()

    sent = make()
    assert got["data"] == sent["data"]
    for field, value in sent.items():
        if field != "data":
            assert got[field] == value


@pytest.mark.parametrize(("route", "make"), KINDS)
def test_rows_are_encrypted_at_rest(as_user, os_client, route, make):
    as_user(ALICE).put(f"/v1/{route}/item-1", json=make())

    index = CHATS.index if route == "chats" else ARTIFACTS.index
    stored = os_client.docs[index]["item-1"]
    assert isinstance(stored["payload"], str)
    assert SECRET_FIGURE not in repr(stored)
    assert "8123456.78" not in repr(stored)
    assert stored["owner"] == "keycloak:u-alice"


@pytest.mark.parametrize(("route", "make"), KINDS)
def test_lists_carry_no_content(as_user, route, make):
    as_user(ALICE).put(f"/v1/{route}/item-1", json=make())

    (item,) = as_user(ALICE).get(f"/v1/{route}").json()["items"]

    assert "data" not in item
    assert "payload" not in item
    assert "owner" not in item
    assert SECRET_FIGURE not in repr(item)


@pytest.mark.parametrize(("route", "make"), KINDS)
def test_replacing_keeps_created_at_and_moves_updated_at(as_user, route, make):
    client = as_user(ALICE)
    first = client.put(f"/v1/{route}/item-1", json=make()).json()

    second = client.put(f"/v1/{route}/item-1", json=make()).json()

    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] > first["updated_at"]


@pytest.mark.parametrize(("route", "make"), KINDS)
def test_lists_are_newest_first(as_user, route, make):
    client = as_user(ALICE)
    for item_id in ("older", "newer"):
        client.put(f"/v1/{route}/{item_id}", json=make())
    # Replacing the older one does not move it: the order is creation order,
    # as the sidebar and the gallery always showed it.
    client.put(f"/v1/{route}/older", json=make())

    assert [i["id"] for i in client.get(f"/v1/{route}").json()["items"]] == ["newer", "older"]


def test_chat_list_can_be_scoped_to_a_workspace(as_user):
    client = as_user(ALICE)
    client.put("/v1/chats/c-1", json=_chat(workspace_id="ws-1"))
    client.put("/v1/chats/c-2", json=_chat(workspace_id="ws-2"))

    scoped = client.get("/v1/chats", params={"workspace_id": "ws-2"}).json()["items"]

    assert [c["id"] for c in scoped] == ["c-2"]
    assert len(client.get("/v1/chats").json()["items"]) == 2


def test_artifact_list_can_be_scoped_to_a_workspace_and_env(as_user):
    """The gallery shows the sidebar's workspace and env only: dev and prod
    hold different figures, so a prod artifact listed under dev reads as dev."""
    client = as_user(ALICE)
    for item_id, workspace_id, env in [
        ("a-dev", "ws-1", "dev"),
        ("a-prod", "ws-1", "prod"),
        ("a-other", "ws-2", "dev"),
    ]:
        client.put(f"/v1/artifacts/{item_id}", json={**_artifact(), "workspace_id": workspace_id, "env": env})

    def ids(**params: str) -> list[str]:
        return [a["id"] for a in client.get("/v1/artifacts", params=params).json()["items"]]

    assert ids(workspace_id="ws-1", env="dev") == ["a-dev"]
    assert ids(workspace_id="ws-1", env="prod") == ["a-prod"]
    assert ids(workspace_id="ws-1") == ["a-prod", "a-dev"]
    assert sorted(ids()) == ["a-dev", "a-other", "a-prod"]
    assert client.get("/v1/artifacts", params={"env": "qa"}).status_code == 422


def test_a_list_cannot_filter_on_an_undeclared_field(os_client):
    """Only the cleartext list fields of a kind can filter; anything else would
    be a term query on a field the strict mapping does not have."""
    with pytest.raises(ValueError):
        UserStore(CHATS, client=os_client).list("keycloak:u-alice", {"env": "dev"})


def test_a_deleted_chat_is_gone(as_user):
    client = as_user(ALICE)
    client.put("/v1/chats/c-1", json=_chat())

    assert client.delete("/v1/chats/c-1").status_code == 204
    assert client.get("/v1/chats/c-1").status_code == 404
    assert client.get("/v1/chats").json() == {"items": []}


def test_a_token_without_sub_cannot_save(as_user):
    """Otherwise every token lacking a `sub` would share one owner."""
    no_sub = TokenClaims(sub="", email="x@onibex.com", roles=[], issuer="keycloak")

    resp = as_user(no_sub).put("/v1/chats/c-1", json=_chat())

    assert resp.status_code == 401
    assert resp.json()["detail"]["error_code"] == "TOKEN_WITHOUT_SUBJECT"


def test_an_oversized_item_is_refused_and_not_written(as_user, os_client, monkeypatch):
    monkeypatch.setattr(user_store, "MAX_PAYLOAD_BYTES", 100)

    resp = as_user(ALICE).put("/v1/artifacts/a-1", json=_artifact())

    assert resp.status_code == 413
    assert resp.json()["detail"]["error_code"] == "PAYLOAD_TOO_LARGE"
    assert os_client.docs[ARTIFACTS.index] == {}


def test_an_item_under_another_key_says_so_and_the_list_still_works(as_user, monkeypatch):
    """A key change without the rotation script: the item cannot be read, the
    error says why, and the list (cleartext metadata) keeps working."""
    as_user(ALICE).put("/v1/artifacts/a-1", json=_artifact())
    monkeypatch.setenv("ONIBEX_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_cache_for_tests()

    resp = as_user(ALICE).get("/v1/artifacts/a-1")

    assert resp.status_code == 500
    assert resp.json()["detail"]["error_code"] == "SAVED_ITEM_UNREADABLE"
    assert [a["id"] for a in as_user(ALICE).get("/v1/artifacts").json()["items"]] == ["a-1"]


@pytest.mark.parametrize("bad_id", ["a.b", "a b", "x" * 129])
def test_ids_outside_the_browsers_alphabet_are_refused(as_user, bad_id):
    assert as_user(ALICE).put(f"/v1/chats/{bad_id}", json=_chat()).status_code == 422


def test_an_artifact_env_outside_dev_and_prod_is_refused(as_user):
    assert as_user(ALICE).put("/v1/artifacts/a-1", json={**_artifact(), "env": "qa"}).status_code == 422


def _rotation_script():
    """``platform/scripts/rotate_master_key.py``, loaded by path: scripts/ is
    not a package."""
    path = Path(__file__).resolve().parents[4] / "scripts" / "rotate_master_key.py"
    spec = importlib.util.spec_from_file_location("rotate_master_key", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_rotation_script_covers_every_index_the_store_writes():
    """The script names the indices instead of importing them (it also runs
    where ask_orchestrator is not installed); this keeps the two in step."""
    assert set(_rotation_script().SAVED_ITEM_INDICES) == {CHATS.index, ARTIFACTS.index}


def test_saved_items_survive_a_key_rotation(os_client, monkeypatch):
    """Without the rotation, a key change leaves every saved chat and artifact
    unreadable. After it, the new key alone reads them, and the lists keep
    their dates."""
    script = _rotation_script()
    chats, artifacts = UserStore(CHATS, client=os_client), UserStore(ARTIFACTS, client=os_client)
    chat, artifact = _chat(), _artifact()
    chats.put("keycloak:u-alice", "", "c-1", chat, chat["data"])
    artifacts.put("keycloak:u-alice", "", "a-1", artifact, artifact["data"])
    def stamps() -> dict[tuple[str, str], str]:
        return {
            (index, doc_id): doc["updated_at"]
            for index in (CHATS.index, ARTIFACTS.index)
            for doc_id, doc in os_client.docs[index].items()
        }

    before = stamps()

    old_key = os.environ["ONIBEX_ENCRYPTION_KEY"].encode()
    new_key = Fernet.generate_key()
    monkeypatch.setattr(
        script.helpers,
        "scan",
        lambda client, index, query, _source: [
            {"_id": doc_id, "_source": {"payload": doc["payload"]}}
            for doc_id, doc in client.docs[index].items()
        ],
    )

    rotated = script.rotate_saved_items(os_client, MultiFernet([Fernet(new_key), Fernet(old_key)]))

    assert rotated == 2
    monkeypatch.setenv("ONIBEX_ENCRYPTION_KEY", new_key.decode())
    crypto.reset_cache_for_tests()
    assert chats.get("keycloak:u-alice", "c-1")["data"] == chat["data"]
    assert artifacts.get("keycloak:u-alice", "a-1")["data"] == artifact["data"]
    assert stamps() == before


@pytest.mark.parametrize("kind", [CHATS, ARTIFACTS], ids=["chats", "artifacts"])
def test_the_index_never_parses_payload(kind):
    """Rows indexed would turn every result column into an index field: the
    1,000-field limit, and a hard failure when two results type the same
    column differently."""
    mappings = kind.mapping()["mappings"]

    assert mappings["dynamic"] == "strict"
    assert mappings["properties"]["payload"] == {"type": "object", "enabled": False}
