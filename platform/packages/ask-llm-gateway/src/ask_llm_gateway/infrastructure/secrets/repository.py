"""OpenSearch CRUD for the ``ask-system-settings-v1`` index.

Two singleton documents live in this index:

  * ``_id = "llm"``       — current LLM provider config
  * ``_id = "embedder"``  — current Embedder provider config

Doc shape:

  {
    "provider":   "bedrock",
    "model":      "bedrock/converse/us.amazon.nova-lite-v1:0",
    "plain":      { "AWS_REGION": "us-east-2" },
    "encrypted":  { "AWS_BEARER_TOKEN_BEDROCK": "gAAA..." },
    "updated_at": "2026-06-04T22:30:00Z",
    "updated_by": "admin@example.com"
  }

The ``encrypted`` sub-object is mapped with ``enabled: false`` so OpenSearch
stores it but does NOT index it — defense-in-depth in case anyone tries to
query the index directly.

OpenSearch connection mirrors the pattern used by
``WorkspaceRepository``: read host/port/auth from ``settings.json`` (with env
overrides). This module CANNOT depend on SecretsProvider — chicken-and-egg.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC
from pathlib import Path
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from .crypto import decrypt, encrypt
from .registry import db_provider_fields, provider_fields

logger = logging.getLogger(__name__)


INDEX_SYSTEM_SETTINGS = "ask-system-settings-v1"

# Legacy per-environment DB-config targets (2026-07 migration, singleton per
# env). Superseded by the connection registry below but kept as a runtime
# fallback + one-time import source. They share the index with llm/embedder but
# route through the DB field registry, not the LLM one.
_DB_TARGETS: frozenset[str] = frozenset({"db_dev", "db_prod"})

# Connection registry (2026-07 multi-DB). Each registered database connection is
# its own doc ``dbconn:<id>`` (same encrypted shape as the legacy db docs, plus a
# display ``name``). A single pointer doc ``db_active`` records which connection
# is active per environment: ``plain = {"dev": "<id>", "prod": "<id>"}``.
CONN_PREFIX = "dbconn:"
ACTIVE_POINTER_ID = "db_active"

# LLM connection registry (2026-07 multi-LLM). Mirrors the DB registry above but
# the active pointer is SINGLE-VALUED (one global active LLM — no dev/prod). The
# active connection is ALSO projected into the ``llm`` singleton doc the runtime
# reads (``factory.build_llm``), so the hot path stays unchanged. Design ref:
# internal design doc (ITERATION_LLM_PROVIDERS_REGISTRY_PLAN).
LLM_CONN_PREFIX = "llmconn:"
LLM_ACTIVE_POINTER_ID = "llm_active"

# Whitelist of the FIXED doc ids the index holds. Connection docs
# (``dbconn:*`` / ``llmconn:*``) and the pointer docs are allowed by pattern in
# ``_validate_target``.
_KNOWN_TARGETS: frozenset[str] = frozenset({"llm", "embedder"}) | _DB_TARGETS


_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "provider": {"type": "keyword"},
            "model": {"type": "keyword"},
            "name": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "plain": {"type": "object", "enabled": True},
            "encrypted": {"type": "object", "enabled": False},
            "updated_at": {"type": "keyword"},
            "updated_by": {"type": "keyword"},
        }
    }
}


class SecretsRepository:
    """Thin wrapper around OpenSearch for the ``ask-system-settings-v1`` index.

    All callers should hit ``SecretsProvider`` instead. The repository is
    plumbing — no caching, no env-var export, no validation beyond shape.
    """

    def __init__(self, client: OpenSearch | None = None) -> None:
        self._client = client or _build_client()
        self._index_ensured = False

    # ── Index lifecycle ─────────────────────────────────────────────────────

    def ensure_index(self) -> None:
        """Idempotent — create the index if missing. Called lazily on first I/O.

        Retries up to 3 times with exponential back-off to tolerate the Windows
        10053 (WSAECONNABORTED) race condition where OpenSearch accepts the TCP
        handshake but aborts the first HTTP request while still warming up.
        """
        if self._index_ensured:
            return
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                if not self._client.indices.exists(index=INDEX_SYSTEM_SETTINGS):
                    self._client.indices.create(index=INDEX_SYSTEM_SETTINGS, body=_MAPPING)
                    logger.info("Created OpenSearch index %s", INDEX_SYSTEM_SETTINGS)
                self._index_ensured = True
                return
            except Exception as exc:
                last_exc = exc
                wait = 0.5 * (2**attempt)  # 0.5 s, 1 s, 2 s
                logger.warning(
                    "ensure_index attempt %d/3 failed (%s); retrying in %.1fs",
                    attempt + 1,
                    exc,
                    wait,
                )
                time.sleep(wait)
        logger.exception("Failed to ensure index %s after 3 attempts", INDEX_SYSTEM_SETTINGS)
        raise last_exc  # type: ignore[misc]

    # ── Raw doc R/W ─────────────────────────────────────────────────────────

    def get_raw(self, target: str) -> dict[str, Any] | None:
        """Return the doc as-stored (encrypted tokens still in ``encrypted``).

        Used by the rotation script and by the GET endpoint (which masks
        encrypted values before responding to the SPA).
        """
        _validate_target(target)
        self.ensure_index()
        try:
            doc = self._client.get(index=INDEX_SYSTEM_SETTINGS, id=target)
            return dict(doc["_source"])
        except NotFoundError:
            return None

    def upsert_raw(self, target: str, doc: dict[str, Any]) -> None:
        """Write a doc as-given. Caller is responsible for the shape.

        Used by the migration script + the rotation script (already-encrypted
        values). End-user writes go through ``upsert``.
        """
        _validate_target(target)
        self.ensure_index()
        self._client.index(
            index=INDEX_SYSTEM_SETTINGS,
            id=target,
            body=doc,
            refresh="wait_for",
        )

    # ── High-level upsert ──────────────────────────────────────────────────

    def upsert(
        self,
        target: str,
        *,
        provider: str,
        model: str,
        fields: dict[str, str],
        updated_by: str,
        preserve_blank_secrets: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Split ``fields`` into plain vs encrypted (per registry) + persist.

        Returns the stored doc (with encrypted sub-object containing Fernet
        tokens — caller should mask before sending to the SPA).

        ``preserve_blank_secrets`` (DB write path): when True, a sensitive field
        that arrives blank but already exists (encrypted) in the stored doc
        keeps its current ciphertext instead of being cleared. Lets the admin
        edit non-secret fields (host / port) without re-typing the password.
        Skipped when the provider changed (a stored secret from a different
        backend must never carry over — the admin re-enters it).

        ``extra`` merges additional top-level keys into the stored doc (e.g.
        ``name`` / ``kind`` for connection-registry docs). Reserved keys
        (provider/model/plain/encrypted/updated_at/updated_by) cannot be
        overridden.
        """
        _validate_target(target)
        self.ensure_index()

        plain, encrypted = _split_by_registry(provider, fields, target=target)

        if preserve_blank_secrets:
            existing = self.get_raw(target) or {}
            if existing.get("provider") == provider:
                existing_enc = existing.get("encrypted") or {}
                for name, sensitive in _registry_entries(target, provider).items():
                    blank = fields.get(name) in (None, "")
                    if sensitive and blank and name not in encrypted and name in existing_enc:
                        encrypted[name] = existing_enc[name]

        doc: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "plain": plain,
            "encrypted": encrypted,
            "updated_at": _now_iso(),
            "updated_by": updated_by,
        }
        if extra:
            _reserved = {"provider", "model", "plain", "encrypted", "updated_at", "updated_by"}
            for key, value in extra.items():
                if key not in _reserved:
                    doc[key] = value
        self._client.index(
            index=INDEX_SYSTEM_SETTINGS,
            id=target,
            body=doc,
            refresh="wait_for",
        )
        return doc

    # ── Decrypt + merge ─────────────────────────────────────────────────────

    def get_resolved(self, target: str) -> dict[str, Any] | None:
        """Return the doc with ``encrypted`` decrypted in-place.

        The runtime consumer (SecretsProvider → factory.build_llm) needs the
        plaintext to seed os.environ for LiteLLM / boto3. Raises
        PermissionError if a stored cipher does not match the current master
        key (caller catches and surfaces a 503).
        """
        raw = self.get_raw(target)
        if raw is None:
            return None
        plain = dict(raw.get("plain") or {})
        decrypted: dict[str, str] = {}
        for k, token in (raw.get("encrypted") or {}).items():
            decrypted[k] = decrypt(token)
        return {
            "provider": raw.get("provider", ""),
            "model": raw.get("model", ""),
            "name": raw.get("name", ""),
            "fields": {**plain, **decrypted},
            "plain_keys": list(plain.keys()),
            "encrypted_keys": list((raw.get("encrypted") or {}).keys()),
            "updated_at": raw.get("updated_at", ""),
            "updated_by": raw.get("updated_by", ""),
        }

    def delete(self, target: str) -> bool:
        _validate_target(target)
        self.ensure_index()
        try:
            self._client.delete(index=INDEX_SYSTEM_SETTINGS, id=target, refresh="wait_for")
            return True
        except NotFoundError:
            return False

    # ── Connection registry (multi-DB) ──────────────────────────────────────

    def list_db_connections(self) -> list[tuple[str, dict[str, Any]]]:
        """Return ``[(doc_id, raw_doc), ...]`` for every ``dbconn:*`` doc.

        Uses a bounded ``match_all`` search + Python-side prefix filter so it
        works regardless of how ``_id`` is mapped (a ``prefix`` query on ``_id``
        is not portable). Connection counts are tiny (a handful), so ``size``
        1000 is comfortably above any real registry.
        """
        self.ensure_index()
        try:
            resp = self._client.search(
                index=INDEX_SYSTEM_SETTINGS,
                body={"query": {"match_all": {}}, "size": 1000},
            )
        except NotFoundError:
            return []
        hits = resp.get("hits", {}).get("hits", [])
        out: list[tuple[str, dict[str, Any]]] = []
        for hit in hits:
            doc_id = str(hit.get("_id", ""))
            if doc_id.startswith(CONN_PREFIX):
                out.append((doc_id, dict(hit.get("_source") or {})))
        out.sort(key=lambda pair: str(pair[1].get("updated_at") or ""))
        return out

    def get_active(self) -> dict[str, str]:
        """Return the active-connection pointer ``{"dev": id, "prod": id}``.

        Missing slots are absent from the dict (never ``""``). Empty dict when
        the pointer doc does not exist yet.
        """
        raw = self.get_raw(ACTIVE_POINTER_ID)
        if raw is None:
            return {}
        plain = dict(raw.get("plain") or {})
        return {env: str(cid) for env, cid in plain.items() if env in ("dev", "prod") and cid}

    def set_active(self, mapping: dict[str, str | None], *, updated_by: str) -> dict[str, str]:
        """Overwrite the active pointer. ``None`` / blank clears that env slot.

        Stores the pointer as a plain (unencrypted) doc so the runtime resolver
        can read it through the same cached provider path as the connection docs.
        Returns the resulting ``{"dev": id, "prod": id}`` (only set slots).
        """
        plain: dict[str, str] = {}
        for env in ("dev", "prod"):
            cid = mapping.get(env)
            if cid:
                plain[env] = str(cid)
        self.upsert_raw(
            ACTIVE_POINTER_ID,
            {
                "plain": plain,
                "encrypted": {},
                "kind": "db_active_pointer",
                "updated_at": _now_iso(),
                "updated_by": updated_by,
            },
        )
        return plain

    # ── LLM connection registry (multi-LLM, SINGLE active — 2026-07) ─────────

    def list_llm_connections(self) -> list[tuple[str, dict[str, Any]]]:
        """Return ``[(doc_id, raw_doc), ...]`` for every ``llmconn:*`` doc.

        Same bounded ``match_all`` + Python-side prefix filter as
        :meth:`list_db_connections` — portable regardless of ``_id`` mapping.
        """
        self.ensure_index()
        try:
            resp = self._client.search(
                index=INDEX_SYSTEM_SETTINGS,
                body={"query": {"match_all": {}}, "size": 1000},
            )
        except NotFoundError:
            return []
        hits = resp.get("hits", {}).get("hits", [])
        out: list[tuple[str, dict[str, Any]]] = []
        for hit in hits:
            doc_id = str(hit.get("_id", ""))
            if doc_id.startswith(LLM_CONN_PREFIX):
                out.append((doc_id, dict(hit.get("_source") or {})))
        out.sort(key=lambda pair: str(pair[1].get("updated_at") or ""))
        return out

    def get_active_llm(self) -> str | None:
        """Return the active LLM connection id, or ``None`` when unset."""
        raw = self.get_raw(LLM_ACTIVE_POINTER_ID)
        if raw is None:
            return None
        cid = (raw.get("plain") or {}).get("id")
        return str(cid) if cid else None

    def set_active_llm(self, cid: str | None, *, updated_by: str) -> str | None:
        """Overwrite the single-valued active-LLM pointer. ``None`` clears it.

        Stored as a plain (unencrypted) doc so the runtime reads it through the
        same cached path as the connection docs.
        """
        plain: dict[str, str] = {}
        if cid:
            plain["id"] = str(cid)
        self.upsert_raw(
            LLM_ACTIVE_POINTER_ID,
            {
                "plain": plain,
                "encrypted": {},
                "kind": "llm_active_pointer",
                "updated_at": _now_iso(),
                "updated_by": updated_by,
            },
        )
        return cid or None

    def project_active_llm(self, cid: str | None, *, updated_by: str) -> dict[str, Any]:
        """Materialize the active connection into the canonical ``llm`` doc.

        The runtime (``factory.build_llm``) reads the fixed ``llm`` target.
        Rather than teach it to resolve the pointer live, we copy the active
        connection's doc into ``llm`` on every activate / edit-of-active
        (ciphertext preserved — no decrypt round-trip). ``cid`` ``None`` or a
        missing / blank connection → an empty-provider ``llm`` doc, so the
        runtime deterministically reports "no LLM configured" instead of using a
        stale value. Returns the projected doc.
        """
        raw = self.get_raw(cid) if cid else None
        if raw and raw.get("provider"):
            doc: dict[str, Any] = {
                "provider": str(raw.get("provider") or ""),
                "model": str(raw.get("model") or ""),
                "plain": dict(raw.get("plain") or {}),
                "encrypted": dict(raw.get("encrypted") or {}),
                "updated_at": _now_iso(),
                "updated_by": updated_by,
            }
        else:
            doc = {
                "provider": "",
                "model": "",
                "plain": {},
                "encrypted": {},
                "updated_at": _now_iso(),
                "updated_by": updated_by,
            }
        self.upsert_raw("llm", doc)
        return doc


# ── Helpers ─────────────────────────────────────────────────────────────────


def _validate_target(target: str) -> None:
    if (
        target in _KNOWN_TARGETS
        or target == ACTIVE_POINTER_ID
        or target == LLM_ACTIVE_POINTER_ID
        or target.startswith(CONN_PREFIX)
        or target.startswith(LLM_CONN_PREFIX)
    ):
        return
    raise ValueError(
        f"Unknown secrets target {target!r} — expected one of {sorted(_KNOWN_TARGETS)}, "
        f"the {ACTIVE_POINTER_ID!r}/{LLM_ACTIVE_POINTER_ID!r} pointer, or a "
        f"{CONN_PREFIX!r}*/{LLM_CONN_PREFIX!r}* connection id"
    )


def _is_db_target(target: str | None) -> bool:
    """True for any target that stores a DB connection (legacy env docs or a
    ``dbconn:*`` registry doc) — these route through the DB field registry."""
    return bool(target) and (target in _DB_TARGETS or str(target).startswith(CONN_PREFIX))


def _registry_entries(target: str | None, provider: str) -> dict[str, bool]:
    """Return ``{field_name: is_sensitive}`` for ``provider`` under ``target``.

    DB targets (``db_dev`` / ``db_prod`` / ``dbconn:*``) route through the DB
    registry — the LLM registry would collide on shared ids like ``databricks``.
    Everything else uses the LLM/embedder registry.
    """
    if _is_db_target(target):
        return {fname: sensitive for fname, sensitive, _kind in db_provider_fields(provider)}
    return {fname: sensitive for fname, sensitive in provider_fields(provider)}


def _split_by_registry(
    provider: str, fields: dict[str, str], target: str | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Use the per-provider registry to route each incoming field.

    Unknown fields (not in the registry for this provider) are dropped silently
    — the registry is the contract; admin clients can submit a superset and the
    backend keeps it clean.

    Empty strings (`""`) are treated as "delete this field" and end up in
    neither bucket.

    ``target`` selects the registry plane (DB targets use the DB registry);
    ``None`` (the default) uses the LLM/embedder registry — back-compat.
    """
    plain: dict[str, str] = {}
    encrypted: dict[str, str] = {}
    registry = _registry_entries(target, provider)
    for name, value in fields.items():
        if value == "" or value is None:
            continue  # delete intent
        if name not in registry:
            continue  # not declared for this provider — drop
        if registry[name]:
            encrypted[name] = encrypt(str(value))
        else:
            plain[name] = str(value)
    return plain, encrypted


def _build_client() -> OpenSearch:
    """Read OpenSearch connection from env (preferred) or ``settings.json``.

    Env vars win — that's how this module survives the cleanup that strips the
    ``opensearch`` block from ``settings.json``. The fallback keeps existing
    dev environments working until they migrate.
    """
    host = os.getenv("OPENSEARCH_HOST")
    port_env = os.getenv("OPENSEARCH_PORT")
    use_ssl_env = os.getenv("OPENSEARCH_USE_SSL")
    username = os.getenv("OPENSEARCH_USER") or None
    password = os.getenv("OPENSEARCH_PASSWORD") or None

    if not host:
        cfg = _read_settings_safely()
        os_cfg = cfg.get("opensearch") or {}
        host = os_cfg.get("host", "localhost")
        port = int(port_env or os_cfg.get("port", 9200))
        use_ssl = (
            bool(os_cfg.get("use_ssl", False)) if use_ssl_env is None else _truthy(use_ssl_env)
        )
        username = username or os_cfg.get("username") or None
        password = password or os_cfg.get("password") or None
        verify_certs = bool(os_cfg.get("verify_certs", False))
    else:
        port = int(port_env or 9200)
        use_ssl = _truthy(use_ssl_env or "")
        verify_certs = _truthy(os.getenv("OPENSEARCH_VERIFY_CERTS", ""))

    kwargs: dict[str, Any] = {
        "hosts": [{"host": host, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": verify_certs,
        "ssl_show_warn": False,
    }
    if username and password:
        kwargs["http_auth"] = (username, password)
    return OpenSearch(**kwargs)


def _read_settings_safely() -> dict[str, Any]:
    path = Path("config/settings.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not parse settings.json — using OpenSearch defaults")
        return {}


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _now_iso() -> str:
    """Local helper instead of importing a heavy dep — keeps the module light."""
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def new_connection_id() -> str:
    """Return a fresh ``dbconn:<hex>`` id for a new registry connection."""
    import uuid

    return f"{CONN_PREFIX}{uuid.uuid4().hex[:12]}"


def new_llm_connection_id() -> str:
    """Return a fresh ``llmconn:<hex>`` id for a new LLM registry connection."""
    import uuid

    return f"{LLM_CONN_PREFIX}{uuid.uuid4().hex[:12]}"
