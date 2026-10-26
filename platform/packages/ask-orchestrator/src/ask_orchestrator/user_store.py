# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Per-user storage for ASK Chat's chats and artifacts.

The chat SPA used to keep both in the browser's ``localStorage``. A chat or an
artifact made in one browser did not exist in another, and since the storage
key carried no user and signing out did not clear it, the next person to sign
in on the same browser saw the previous user's chats and artifacts, result rows
included. Both now live in OpenSearch, one document each, owned by the user
who wrote it.

The browser still builds the chat and the artifact exactly as before; this
store only keeps them. One index per kind, both with the same shape:

* ``owner`` (``<issuer>:<sub>`` of the validated token), which every read and
  write filters on, plus the few cleartext fields a list needs;
* ``payload``: everything else, Fernet-encrypted with ``ONIBEX_ENCRYPTION_KEY``.
  Chats and artifacts carry query result rows, and OpenSearch runs without
  authentication in the compose stack, so the figures must not depend on each
  server's firewall.

``payload`` is mapped ``enabled: false``: OpenSearch keeps it in ``_source``
and never parses it. Indexed, every column of every result set would become a
field of the index, which hits the 1,000-field limit and fails outright the
first time two results bring the same column name with different types. The
mapping is ``dynamic: strict`` so nothing else can slip in either.

``scripts/rotate_master_key.py`` re-encrypts both indices; a key change that
skips them leaves every saved chat and artifact unreadable.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from ask_llm_gateway.infrastructure.secrets.crypto import decrypt, encrypt

from .workspace_scope import _build_client

logger = logging.getLogger(__name__)

# Ceiling on one stored document, measured on the encrypted payload. OpenSearch
# refuses requests above 100 MB; a chat or artifact anywhere near this is a
# result set nobody reads in a browser, so it is refused with a clear error
# instead of being half-written.
MAX_PAYLOAD_BYTES = 20 * 1024 * 1024

# Lists are not paginated. A user past this many items sees the newest ones and
# the log says so.
MAX_LIST_ITEMS = 500

_KEYWORD: dict[str, Any] = {"type": "keyword"}
_DATE: dict[str, Any] = {"type": "date"}
_TEXT_WITH_KEYWORD: dict[str, Any] = {
    "type": "text",
    "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
}


@dataclass(frozen=True)
class Kind:
    """One kind of saved item: its index and its cleartext list fields."""

    index: str
    fields: dict[str, dict[str, Any]]

    def mapping(self) -> dict[str, Any]:
        return {
            "mappings": {
                "dynamic": "strict",
                "properties": {
                    "owner": _KEYWORD,
                    # Diagnostics only, never access control: an email can be
                    # missing from a token or change, the ``sub`` cannot.
                    "owner_email": _KEYWORD,
                    "created_at": _DATE,
                    "updated_at": _DATE,
                    "payload": {"type": "object", "enabled": False},
                    **self.fields,
                },
            }
        }


CHATS = Kind(
    index="ask-chats-v1",
    fields={"workspace_id": _KEYWORD, "title": _TEXT_WITH_KEYWORD},
)
ARTIFACTS = Kind(
    index="ask-artifacts-v1",
    fields={
        "workspace_id": _KEYWORD,
        "env": _KEYWORD,
        "name": _TEXT_WITH_KEYWORD,
        "artifact_type": _KEYWORD,
        "format": _KEYWORD,
    },
)


class PayloadTooLargeError(ValueError):
    """The encrypted payload is above ``MAX_PAYLOAD_BYTES``."""


def owner_key(issuer: str, sub: str) -> str:
    """The owner of everything a token's user saves. Requires a ``sub``: without
    it, every token lacking one would share a single owner."""
    if not sub:
        raise ValueError("a token without `sub` cannot own saved items")
    return f"{issuer}:{sub}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class UserStore:
    """CRUD over one kind's index. Every operation is scoped to an owner: an
    item that belongs to someone else behaves exactly like one that does not
    exist."""

    def __init__(self, kind: Kind, client: OpenSearch | None = None) -> None:
        self.kind = kind
        self._client = client or _build_client()
        self._index_ensured = False

    def ensure_index(self) -> None:
        if self._index_ensured:
            return
        index = self.kind.index
        if not self._client.indices.exists(index=index):
            self._client.indices.create(index=index, body=self.kind.mapping())
            logger.info("Created OpenSearch index %s", index)
        self._index_ensured = True

    def list(self, owner: str, workspace_id: str | None = None) -> list[dict[str, Any]]:
        """The owner's items, newest first, without ``payload``."""
        self.ensure_index()
        filters: list[dict[str, Any]] = [{"term": {"owner": owner}}]
        if workspace_id:
            filters.append({"term": {"workspace_id": workspace_id}})
        resp = self._client.search(
            index=self.kind.index,
            body={
                "query": {"bool": {"filter": filters}},
                "sort": [{"created_at": {"order": "desc"}}],
                "size": MAX_LIST_ITEMS,
                "_source": {"excludes": ["payload", "owner", "owner_email"]},
            },
        )
        hits = resp["hits"]["hits"]
        if len(hits) >= MAX_LIST_ITEMS:
            logger.warning(
                "%s list for one owner hit the %d cap; older items are not returned",
                self.kind.index,
                MAX_LIST_ITEMS,
            )
        return [{"id": h["_id"], **h["_source"]} for h in hits]

    def get(self, owner: str, item_id: str) -> dict[str, Any] | None:
        """The item with its decrypted payload under ``data``, or ``None``.

        Raises ``PermissionError`` when the payload does not decrypt (the key
        changed without running the rotation script).
        """
        source = self._owned_source(owner, item_id)
        if source is None:
            return None
        meta = {k: v for k, v in source.items() if k not in ("payload", "owner", "owner_email")}
        return {"id": item_id, **meta, "data": json.loads(decrypt(source["payload"]))}

    def put(
        self,
        owner: str,
        owner_email: str,
        item_id: str,
        meta: dict[str, Any],
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Create or replace an item. Returns its list entry, or ``None`` when
        the id belongs to another owner (which is never overwritten)."""
        self.ensure_index()
        try:
            existing = self._client.get(index=self.kind.index, id=item_id)["_source"]
        except NotFoundError:
            existing = None
        if existing is not None and existing.get("owner") != owner:
            return None

        payload = encrypt(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise PayloadTooLargeError(
                f"This item is {len(payload) // (1024 * 1024)} MB once encrypted; "
                f"the limit is {MAX_PAYLOAD_BYTES // (1024 * 1024)} MB."
            )

        now = _now()
        entry = {
            **{k: meta.get(k) for k in self.kind.fields},
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        self._client.index(
            index=self.kind.index,
            id=item_id,
            body={**entry, "owner": owner, "owner_email": owner_email, "payload": payload},
            refresh="wait_for",
        )
        return {"id": item_id, **entry}

    def delete(self, owner: str, item_id: str) -> bool:
        """``False`` when there is nothing of this owner's to delete."""
        if self._owned_source(owner, item_id) is None:
            return False
        try:
            self._client.delete(index=self.kind.index, id=item_id, refresh="wait_for")
        except NotFoundError:
            return False
        return True

    def _owned_source(self, owner: str, item_id: str) -> dict[str, Any] | None:
        self.ensure_index()
        try:
            source = self._client.get(index=self.kind.index, id=item_id)["_source"]
        except NotFoundError:
            return None
        return source if source.get("owner") == owner else None


_stores: dict[str, UserStore] = {}
_stores_lock = threading.Lock()


def _store(kind: Kind) -> UserStore:
    with _stores_lock:
        if kind.index not in _stores:
            _stores[kind.index] = UserStore(kind)
        return _stores[kind.index]


def get_chat_store() -> UserStore:
    """FastAPI dependency; tests override it."""
    return _store(CHATS)


def get_artifact_store() -> UserStore:
    """FastAPI dependency; tests override it."""
    return _store(ARTIFACTS)
