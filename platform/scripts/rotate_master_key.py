# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Re-encrypt every encrypted-secrets doc with a NEW master key.

Required env vars during the rotation window (BOTH at once):

  ONIBEX_ENCRYPTION_KEY      → the NEW key
  ONIBEX_ENCRYPTION_KEY_OLD  → the OLD key (drop after the script finishes)

After this runs, point the deployment manifests at the new key and remove the
``_OLD`` value from the K8s Secret. No downtime — MultiFernet decrypts with
either key during the window.

See ``docs/HANDOFF_encrypted_secrets_opensearch.md`` §13.

The same key encrypts every saved chat and artifact of ASK Chat (the
``payload`` field of the indices in ``SAVED_ITEM_INDICES``); those are
re-encrypted too.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from cryptography.fernet import Fernet, MultiFernet
from opensearchpy import OpenSearch, helpers

from ask_llm_gateway.infrastructure.secrets import SecretsRepository
from ask_llm_gateway.infrastructure.secrets.repository import _build_client

# The indices of ``ask_orchestrator.user_store``. Named here rather than
# imported because this script also runs where the orchestrator package is not
# installed (the admin-api image); a test keeps the two lists equal.
SAVED_ITEM_INDICES = ("ask-chats-v1", "ask-artifacts-v1")


def rotate_saved_items(client: OpenSearch, multi: MultiFernet) -> int:
    """Re-encrypt the ``payload`` of every saved chat and artifact. Returns how
    many were rotated. ``updated_at`` is left alone: a key change is not an
    edit the user made."""
    rotated = 0
    for index in SAVED_ITEM_INDICES:
        if not client.indices.exists(index=index):
            print(f"[skip] {index}: no index")
            continue
        count = 0
        for hit in helpers.scan(client, index=index, query={"query": {"match_all": {}}}, _source=["payload"]):
            token = hit["_source"].get("payload")
            if not token:
                continue
            client.update(
                index=index,
                id=hit["_id"],
                body={"doc": {"payload": multi.rotate(token.encode()).decode()}},
            )
            count += 1
        client.indices.refresh(index=index)
        print(f"[ok]   {index}: rotated {count} payloads")
        rotated += count
    return rotated


def main() -> int:
    new_raw = os.environ.get("ONIBEX_ENCRYPTION_KEY", "").strip()
    old_raw = os.environ.get("ONIBEX_ENCRYPTION_KEY_OLD", "").strip()
    if not new_raw or not old_raw:
        print(
            "[fatal] both ONIBEX_ENCRYPTION_KEY (new) and ONIBEX_ENCRYPTION_KEY_OLD "
            "(old) must be set during rotation",
            file=sys.stderr,
        )
        return 1

    try:
        new = Fernet(new_raw.encode())
        old = Fernet(old_raw.encode())
    except (ValueError, TypeError) as exc:
        print(f"[fatal] invalid key format: {exc}", file=sys.stderr)
        return 1

    multi = MultiFernet([new, old])  # encrypt → new; decrypt → try new, then old
    client = _build_client()
    repo = SecretsRepository(client)

    rotated = 0
    for target in ("llm", "embedder"):
        doc = repo.get_raw(target)
        if doc is None:
            print(f"[skip] {target}: no doc stored")
            continue
        encrypted = doc.get("encrypted") or {}
        if not encrypted:
            print(f"[skip] {target}: no encrypted fields")
            continue
        new_encrypted: dict[str, str] = {}
        for k, token in encrypted.items():
            new_encrypted[k] = multi.rotate(token.encode()).decode()
        doc["encrypted"] = new_encrypted
        doc["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        doc["updated_by"] = "rotation-script"
        repo.upsert_raw(target, doc)
        rotated += 1
        print(f"[ok]   {target}: rotated {len(new_encrypted)} encrypted fields")

    rotated += rotate_saved_items(client, multi)

    if rotated == 0:
        print("[ok]   nothing to rotate")
    else:
        print(
            "[next] verify the runtime with the NEW key alone, then remove "
            "ONIBEX_ENCRYPTION_KEY_OLD from your environment / K8s Secret."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
