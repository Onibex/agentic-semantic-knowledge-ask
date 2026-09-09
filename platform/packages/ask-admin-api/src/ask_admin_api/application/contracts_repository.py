# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""OpenSearch CRUD for the API contracts, one document per environment.

**What this replaced.** ``config/api-config.json``, the last shared writable
file in the platform. It existed in two byte-identical copies, one baked into
the MCP image and one mounted from ``./config``, and the mounted one silently
shadowed the baked one at runtime. A file that a running pod writes is what
forces a ReadWriteOnce volume in Kubernetes, which forces the pod affinity that
kept two backends from scheduling at all.

**Why a dedicated index rather than the settings store.** The encrypted store
(``ask-system-settings-v1``) is built around a registry of
``(field_name, is_sensitive, kind)`` triples so Fernet can encrypt the
sensitive ones. Contracts fit none of that:

  * They are **not secrets.** OData entity sets, keys and field definitions are
    a contract, not a credential, so there is nothing to encrypt and
    ``SecretsRepository`` would buy exactly nothing.
  * They are **one nested document of about 5 KB**, not a flat field list. The
    registry shape cannot describe them without stringifying the whole thing
    into a single field, which is a lie about what is stored.
  * ``SecretsRepository.upsert`` replaces the whole document and
    ``preserve_blank_secrets`` only carries **sensitive** fields forward, so a
    partial save silently drops plain fields. Reusing it here would import that
    hazard for no benefit.

The cost is one more index to operate. It is worth it, and the mapping below
keeps that cost near zero.

**Env-suffixed**, through the same ``env_index`` resolver every other ASK index
uses: ``ask-api-contracts-v1-dev`` and ``ask-api-contracts-v1-prod``. This is
not gold-plating. A contract describes one specific SAP system, and dev and
prod routinely point at different ones; a single file could not express that,
so until now the two were forced to share.

**Upgrading a deployment that had contracts.**
``scripts/migrate_api_contracts_to_opensearch.py`` takes the old file and
writes it here, once per environment, skipping a target that already has data.
Run it once per environment you actually use: a deployment with contracts in
``dev`` and nothing in ``prod`` is a legitimate state, and a ``prod`` MCP
server stays unready, logging the URL it keeps retrying, until somebody saves
them there.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from .env_targets import opensearch_index_for

logger = logging.getLogger(__name__)

INDEX_API_CONTRACTS = "ask-api-contracts-v1"

# One document per environment, so the id is a constant. The environment lives
# in the index name, not in the id, which is what every other env-scoped index
# in the platform does.
_DOC_ID = "contracts"

# What a caller gets when nothing has been saved yet. Same skeleton the file
# based reader returned, so the Setup SPA sees no change.
EMPTY_CONFIG: dict[str, Any] = {"server": {}, "apis": []}

_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            # `enabled: false` stores the document and indexes none of it. The
            # shape of `config` is the customer's OData model, not ours, so any
            # mapping we invented here would be broken by the next contract and
            # would fail the write with a mapping conflict. Nothing searches
            # contracts; the MCP server reads the whole document by id.
            "config": {"type": "object", "enabled": False},
            "updated_at": {"type": "keyword"},
            "updated_by": {"type": "keyword"},
        }
    }
}


class ContractsRepository:
    """Read and write the API contracts of one environment."""

    def __init__(self, client: OpenSearch | None = None, env: str | None = None) -> None:
        self._client = client or _build_client()
        # Resolved once. `opensearch_index_for` raises on an unknown env, so a
        # typo fails here rather than quietly reading an index nobody writes.
        self._index = opensearch_index_for(INDEX_API_CONTRACTS, env)
        self._index_ensured = False

    @property
    def index(self) -> str:
        return self._index

    def ensure_index(self) -> None:
        if self._index_ensured:
            return
        try:
            if not self._client.indices.exists(index=self._index):
                self._client.indices.create(index=self._index, body=_MAPPING)
                logger.info("Created OpenSearch index %s", self._index)
        except Exception:
            logger.exception("Failed to ensure index %s", self._index)
            raise
        self._index_ensured = True

    def get(self) -> dict[str, Any] | None:
        """The stored config, or ``None`` when this environment has none.

        ``None`` and ``{"server": {}, "apis": []}`` mean different things and
        the caller decides which to show: the first is "nobody has saved
        contracts for this environment", the second is "somebody saved an empty
        set". Collapsing them here is how the file-based version made an
        unconfigured deployment look configured.
        """
        self.ensure_index()
        try:
            doc = self._client.get(index=self._index, id=_DOC_ID)
        except NotFoundError:
            return None
        source = doc.get("_source") or {}
        config = source.get("config")
        if not isinstance(config, dict):
            logger.warning(
                "Contracts document in %s has no usable `config` object; treating as absent",
                self._index,
            )
            return None
        return config

    def upsert(self, config: dict[str, Any], updated_by: str) -> dict[str, Any]:
        """Replace this environment's contracts with ``config``.

        A whole-document replace is correct here, unlike in the secrets store:
        the Contracts page always sends the complete set, there is no second
        screen writing a different part of the same document, and there are no
        sensitive fields to carry forward. The test suite pins that a save of a
        smaller set really does shrink the stored document rather than merging
        into the old one, because a silent merge would resurrect entity sets an
        operator had just deleted.
        """
        self.ensure_index()
        body = {
            "config": config,
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "updated_by": updated_by,
        }
        self._client.index(index=self._index, id=_DOC_ID, body=body, refresh="wait_for")
        logger.info(
            "Contracts saved to %s by %s (%d apis)",
            self._index,
            updated_by or "unknown",
            len(config.get("apis") or []),
        )
        return config


def _build_client() -> OpenSearch:
    """The OpenSearch connection, from the environment and nowhere else.

    Same shape as every other repository in this package. There is deliberately
    no file fallback: you cannot read the address of OpenSearch out of
    OpenSearch, so the connection is one of the three things that stays in the
    environment for good.
    """
    host = os.getenv("OPENSEARCH_HOST") or "localhost"
    port = int(os.getenv("OPENSEARCH_PORT") or 9200)
    use_ssl = _truthy(os.getenv("OPENSEARCH_USE_SSL", ""))
    verify_certs = _truthy(os.getenv("OPENSEARCH_VERIFY_CERTS", ""))
    username = os.getenv("OPENSEARCH_USER") or None
    password = os.getenv("OPENSEARCH_PASSWORD") or None

    kwargs: dict[str, Any] = {
        "hosts": [{"host": host, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": verify_certs,
        "ssl_show_warn": False,
        "maxsize": 20,
    }
    if username and password:
        kwargs["http_auth"] = (username, password)
    return OpenSearch(**kwargs)


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")
