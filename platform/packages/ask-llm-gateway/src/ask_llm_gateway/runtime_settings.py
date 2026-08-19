# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Typed model for ``config/settings.json``.

Lives in ``ask-llm-gateway`` because both ``ask-orchestrator`` and
``ask-admin-api`` already depend on it — the only shared package that can
host the schema without creating new dependency edges.

Backward compatible: existing call sites that read the raw ``dict`` from
``SettingsCache.get()`` keep working untouched. New call sites can opt in
via ``SettingsCache.typed()`` (orchestrator side) or call
``RuntimeSettings.from_dict()`` directly to get:

  * Validation at process boot (fails closed on typos in the JSON)
  * IDE autocomplete + type checking
  * One canonical place to evolve the schema as the product changes

Extra unknown keys are tolerated (``extra="allow"``) so adding a new field
to ``settings.json`` doesn't break running services until they upgrade.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Section models ──────────────────────────────────────────────────────────


class HanaSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    host: str = ""
    port: int = 443
    user: str = ""
    password: str = ""
    schema_: str = Field(default="", alias="schema")


class PostgreSQLSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    host: str = ""
    port: int = 5432
    database: str = ""
    user: str = ""
    password: str = ""
    sslmode: str = "require"


class OpenSearchSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    host: str = "localhost"
    port: int = 9200
    username: str = ""
    password: str = ""
    use_ssl: bool = False
    verify_certs: bool = False
    embedding_dim: int = 1024


class LLMSettings(BaseModel):
    """New shape (LiteLLM integration). Coexists with legacy ``deployments.llm``."""

    model_config = ConfigDict(extra="allow")

    provider: str = ""
    model: str = ""
    api_key: str = ""
    api_base: str = ""
    api_version: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class EmbedderSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str = ""
    model: str = ""
    api_key: str = ""
    api_base: str = ""
    api_version: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class SapAiCoreSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    config_path: str = "config/aicore_config.json"


class SapS4HanaSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    host: str = ""
    odata_path: str = ""
    username: str = ""
    password: str = ""
    mcp_url: str = ""
    port: int = 0


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: Literal["managed", "direct", "bypass"] = "managed"


class HybridPipelineSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    anchor_top_k: int = 3
    expand_max_hops: int = 1
    expand_max_total: int = 5
    use_two_pass_flow: bool = True
    max_expansion_rounds: int = 1


class DataProductDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    description: str = ""
    entity_ids: list[str] = Field(default_factory=list)


class PipelineProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    description: str = ""
    data_products: list[str] = Field(default_factory=list)
    extra_entity_ids: list[str] = Field(default_factory=list)


class PipelineV2Settings(BaseModel):
    model_config = ConfigDict(extra="allow")

    active_profile: str = "default"
    profiles: dict[str, PipelineProfile] = Field(default_factory=dict)
    data_products: dict[str, DataProductDefinition] = Field(default_factory=dict)


# ── Root model ──────────────────────────────────────────────────────────────


class RuntimeSettings(BaseModel):
    """Root of ``config/settings.json``.

    Use either :meth:`from_dict` (when you already have the parsed JSON) or
    :meth:`load` (read + parse a file in one step).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Top-level discriminators
    db_type: Literal["hana", "postgresql"] = "postgresql"
    stack_mode: Literal["managed", "direct"] = "direct"
    schema_mode: str = "yaml"
    model_name: str = ""

    # Connection sections
    hana: HanaSettings = Field(default_factory=HanaSettings)
    postgresql: PostgreSQLSettings = Field(default_factory=PostgreSQLSettings)
    opensearch: OpenSearchSettings = Field(default_factory=OpenSearchSettings)

    # LLM + embeddings
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedder: EmbedderSettings = Field(default_factory=EmbedderSettings)
    sap_ai_core: SapAiCoreSettings = Field(default_factory=SapAiCoreSettings)
    deployments: dict[str, str] = Field(
        default_factory=dict
    )  # legacy: {"llm": id, "embeddings": id}

    # Auth
    auth: AuthSettings = Field(default_factory=AuthSettings)

    # SAP ERP write path
    sap_s4hana: SapS4HanaSettings = Field(default_factory=SapS4HanaSettings)

    # Pipeline + retrieval tuning
    pipeline_v2: PipelineV2Settings = Field(default_factory=PipelineV2Settings)
    hybrid_pipeline: HybridPipelineSettings = Field(default_factory=HybridPipelineSettings)

    # ── Constructors ────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeSettings:
        """Validate a parsed-JSON dict. Raises ``pydantic.ValidationError`` on schema errors."""
        return cls.model_validate(data or {})

    @classmethod
    def load(cls, path: str | Path = "config/settings.json") -> RuntimeSettings:
        """Read + validate a JSON settings file. Missing file → ValueError."""
        p = Path(path)
        if not p.exists():
            raise ValueError(f"Runtime settings file not found: {p}")
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
