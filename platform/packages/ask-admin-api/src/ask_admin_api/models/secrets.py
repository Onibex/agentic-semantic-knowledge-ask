# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Pydantic models for ``/v1/admin/secrets/*`` — encrypted provider config.

The shape is deliberately generic: providers declare their fields via the
backend registry (``ask_llm_gateway.infrastructure.secrets.registry``), the
client sends an opaque ``fields`` dict, and the backend splits plain vs
encrypted before persisting.

GET response masks every ``encrypted`` value to ``"***"`` so Fernet tokens
never reach the browser. The SPA never sees the master key or the ciphertext.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SecretsTarget = Literal["llm", "embedder"]


class SecretsPutRequest(BaseModel):
    """Body for ``PUT /v1/admin/secrets/{llm|embedder}``.

    ``fields`` carries the full provider-specific payload; the backend uses
    the registry to decide which keys are sensitive (encrypted) vs plain.
    Unknown keys for the given provider are dropped silently.

    To clear a field, send it with an empty string. To clear a whole config
    section, send ``provider=""`` (caller intent: "no provider configured").
    """

    provider: str = Field(..., min_length=0, description="Provider id (e.g. 'bedrock').")
    model: str = Field("", description="Model id (provider-specific).")
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="Flat key/value map. Backend routes each to plain vs encrypted.",
    )


class SecretsFieldView(BaseModel):
    """One row in the masked GET response."""

    name: str
    value: str  # "***" when sensitive, real value when plain
    sensitive: bool
    source: Literal["plain", "encrypted", "environment", "default"]


class SecretsGetResponse(BaseModel):
    """Body for ``GET /v1/admin/secrets/{llm|embedder}``.

    ``fields`` is provider-aware: the backend uses the registry to enumerate
    every declared field; for each, either the stored value (plain) or
    ``"***"`` (encrypted) or empty (unset) is returned. The SPA renders the
    same generic form regardless of provider.
    """

    target: SecretsTarget
    provider: str
    model: str
    fields: list[SecretsFieldView]
    updated_at: str = ""
    updated_by: str = ""


class SecretsTestRequest(BaseModel):
    """Body for ``POST /v1/admin/secrets/test``.

    Sends a 1-token probe (LLM) or a 1-string embed call (Embedder) against
    the CURRENTLY stored config. Does not accept overrides — to test changes
    before save, PUT them first (write is idempotent + cheap) then call /test.
    """

    target: SecretsTarget


class SecretsTestResponse(BaseModel):
    success: bool
    target: SecretsTarget
    provider: str
    model: str
    latency_ms: int
    detail: str
    error: str | None = None


# ── Provider metadata (drives the SPA edit form per provider) ───────────────


class ProviderFieldSpec(BaseModel):
    """One declared field for a provider. Tells the SPA how to render it."""

    name: str = Field(..., description="Field name (matches the registry).")
    sensitive: bool = Field(..., description="True → password input + Fernet-encrypted at rest.")


class ProviderSpec(BaseModel):
    """Full spec for one provider — id, display label, and its declared fields."""

    id: str
    label: str
    fields: list[ProviderFieldSpec]


class ProvidersListResponse(BaseModel):
    """Body for ``GET /v1/admin/secrets/providers``.

    The SPA reads this once on Edit-dialog mount and renders the correct
    form per provider id. Drift between this and the runtime registry is
    impossible by construction — both share the same Python registry.
    """

    providers: list[ProviderSpec]


# ── DB config secrets (per-environment: dev / prod) — 2026-07 migration ──────

DbEnv = Literal["dev", "prod"]


class DbSecretsPutRequest(BaseModel):
    """Body for ``PUT /v1/admin/secrets/db/{env}``.

    ``db_type`` is the backend id (``hana`` / ``postgresql`` / ...). ``fields``
    is the flat connection map; the backend splits plain vs encrypted via the
    DB registry. A sensitive field left blank is PRESERVED (keeps the stored
    ciphertext) so host-only edits don't require re-typing the password.
    """

    db_type: str = Field(..., min_length=1, description="DB backend id (e.g. 'hana').")
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="Flat connection map. Backend routes each key to plain vs encrypted.",
    )


class DbSecretsGetResponse(BaseModel):
    """Body for ``GET /v1/admin/secrets/db/{env}``.

    Sensitive fields are returned blank (never the ciphertext); their
    ``source`` is ``encrypted`` when a value is stored so the form can show a
    "leave blank to keep" placeholder. ``configured`` is True when the env has
    a usable connection stored.
    """

    env: DbEnv
    db_type: str
    fields: list[SecretsFieldView]
    configured: bool = False
    updated_at: str = ""
    updated_by: str = ""


class DbSecretsDeleteResponse(BaseModel):
    """Body for ``DELETE /v1/admin/secrets/db/{env}`` — clears the env's config."""

    env: DbEnv
    deleted: bool


# ── DB connection registry (multi-DB, 2026-07) ───────────────────────────────
#
# Supersedes the singleton db_dev/db_prod plane above: the admin registers N
# named connections and marks one active PER ENVIRONMENT (dev / prod). The chat
# resolves the active connection for the env it targets. The legacy /db/{env}
# endpoints stay for back-compat + one-time import of existing docs.


class DbProviderFieldSpec(BaseModel):
    """One declared connection field for a DB backend — drives the SPA form."""

    name: str = Field(..., description="Field name (matches the DB registry).")
    sensitive: bool = Field(..., description="True → password input + Fernet-encrypted at rest.")
    kind: str = Field("str", description="Value kind: 'str' | 'int' | 'bool'.")


class DbProviderSpec(BaseModel):
    """Full spec for one DB backend — id, display label, and its declared fields."""

    id: str
    label: str
    fields: list[DbProviderFieldSpec]


class DbProvidersListResponse(BaseModel):
    """Body for ``GET /v1/admin/secrets/db/providers``.

    The SPA reads this once to render the correct connection form per engine.
    Same registry the runtime uses — no drift possible.
    """

    providers: list[DbProviderSpec]


class DbConnectionView(BaseModel):
    """A registered connection in the masked list/detail view.

    Sensitive fields are returned blank (source ``encrypted`` when stored) so
    the form shows a "leave blank to keep" placeholder. Ciphertext never leaves
    the server.
    """

    id: str
    name: str
    db_type: str
    fields: list[SecretsFieldView]
    configured: bool = False
    updated_at: str = ""
    updated_by: str = ""


class DbActiveView(BaseModel):
    """Which connection id is active per environment (null when unset)."""

    dev: str | None = None
    prod: str | None = None


class DbConnectionsListResponse(BaseModel):
    """Body for ``GET /v1/admin/secrets/db/connections``."""

    connections: list[DbConnectionView]
    active: DbActiveView


class DbConnectionUpsertRequest(BaseModel):
    """Body for ``POST /db/connections`` (create) and ``PUT /db/connections/{id}``.

    ``fields`` is the flat connection map; the backend splits plain vs encrypted
    via the DB registry. On update, a sensitive field left blank is PRESERVED.
    """

    name: str = Field(..., min_length=1, description="Human-readable connection name.")
    db_type: str = Field(..., min_length=1, description="DB backend id (e.g. 'snowflake').")
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="Flat connection map. Backend routes each key to plain vs encrypted.",
    )


class DbConnectionDeleteResponse(BaseModel):
    """Body for ``DELETE /db/connections/{id}``."""

    id: str
    deleted: bool


class DbActivePutRequest(BaseModel):
    """Body for ``PUT /db/connections/active`` — full desired active state.

    Send the connection id to activate for each env, or ``null`` to clear that
    env slot. Both keys are always sent (the SPA holds the full state).
    """

    dev: str | None = None
    prod: str | None = None


class DbConnectionTestResponse(BaseModel):
    """Body for ``POST /db/connections/{id}/test`` — live connection probe."""

    id: str
    success: bool
    db_type: str
    latency_ms: int
    detail: str
    error: str | None = None


# ── LLM connection registry (multi-LLM, SINGLE active — 2026-07) ──────────────
#
# Mirrors the DB connection registry, but the active pointer is single-valued
# (one global active LLM — NO dev/prod). The active connection is projected into
# the canonical ``llm`` doc the runtime reads (``factory.build_llm``), so no
# runtime change is needed. Provider field specs come from the SHARED
# ``GET /v1/admin/secrets/providers`` (ProviderSpec) — no dedicated providers
# endpoint (unlike DB). The legacy singleton ``llm`` doc is kept as the
# projection and imported into the registry on first list.


class LlmConnectionView(BaseModel):
    """A registered LLM connection in the masked list/detail view.

    Sensitive fields are returned blank (source ``encrypted`` when stored) so
    the form shows a "leave blank to keep" placeholder. Ciphertext never leaves
    the server.
    """

    id: str
    name: str
    provider: str
    model: str
    fields: list[SecretsFieldView]
    configured: bool = False
    updated_at: str = ""
    updated_by: str = ""


class LlmActiveView(BaseModel):
    """Which LLM connection id is active (single, global — null when unset)."""

    active: str | None = None


class LlmConnectionsListResponse(BaseModel):
    """Body for ``GET /v1/admin/secrets/llm/connections``."""

    connections: list[LlmConnectionView]
    active: LlmActiveView


class LlmConnectionUpsertRequest(BaseModel):
    """Body for ``POST /llm/connections`` (create) and ``PUT /llm/connections/{id}``.

    ``fields`` is the flat provider payload; the backend splits plain vs
    encrypted via the LLM registry. On update, a sensitive field left blank is
    PRESERVED (keeps the stored ciphertext).
    """

    name: str = Field(..., min_length=1, description="Human-readable connection name.")
    provider: str = Field(..., min_length=1, description="Provider id (e.g. 'bedrock').")
    model: str = Field("", description="Model id (provider-specific).")
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="Flat key/value map. Backend routes each to plain vs encrypted.",
    )


class LlmConnectionDeleteResponse(BaseModel):
    """Body for ``DELETE /llm/connections/{id}``."""

    id: str
    deleted: bool


class LlmActivePutRequest(BaseModel):
    """Body for ``PUT /llm/connections/active`` — the id to activate.

    Send the connection id to activate globally, or ``null`` to clear the active
    LLM (which blocks chat / SQL generation until one is set again).
    """

    active: str | None = None


class LlmConnectionTestResponse(BaseModel):
    """Body for ``POST /llm/connections/{id}/test`` — in-process LLM probe."""

    id: str
    success: bool
    provider: str
    model: str
    latency_ms: int
    detail: str
    error: str | None = None
