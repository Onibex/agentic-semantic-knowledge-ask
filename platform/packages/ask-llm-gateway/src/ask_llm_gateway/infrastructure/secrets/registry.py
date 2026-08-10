"""Per-provider field registry — drives plain/encrypted split + UI rendering.

Each provider lists the fields its config needs and which ones are sensitive
(must be Fernet-encrypted before persistence). The registry is the single
source of truth consumed by:

  * SecretsRepository — to split incoming ``fields`` into ``plain`` vs ``encrypted``.
  * SecretsProvider   — to know which keys to ``decrypt`` + ``export_to_env``.
  * Admin SPA         — to render the right form per provider (via the API).

Adding a provider = one line here + the corresponding adapter in
``provider_env.py`` / ``litellm_llm.py``.
"""

from __future__ import annotations

# (field_name, is_sensitive)
# Field names match the env vars LiteLLM / provider SDKs expect at runtime.
# Sensitive fields are Fernet-encrypted at rest. Plain fields stay readable in
# OpenSearch (provider IDs, regions, API bases — public-ish metadata).
_PROVIDER_FIELDS: dict[str, list[tuple[str, bool]]] = {
    # Direct LLM providers (via LiteLLM).
    "openai": [
        ("api_key", True),
        ("api_base", False),
    ],
    "anthropic": [
        ("api_key", True),
    ],
    "gemini": [
        ("api_key", True),
    ],
    "azure": [
        ("api_key", True),
        ("api_base", False),
        ("api_version", False),
    ],
    "databricks": [
        ("api_key", True),
        ("api_base", False),
    ],
    "bedrock": [
        # AWS env vars — LiteLLM picks them up from os.environ at call time.
        ("AWS_BEARER_TOKEN_BEDROCK", True),
        ("AWS_ACCESS_KEY_ID", True),
        ("AWS_SECRET_ACCESS_KEY", True),
        ("AWS_SESSION_TOKEN", True),
        ("AWS_REGION", False),
        ("AWS_REGION_NAME", False),
    ],
    "vertex_ai": [
        ("GOOGLE_APPLICATION_CREDENTIALS", True),
        ("VERTEXAI_PROJECT", False),
        ("VERTEXAI_LOCATION", False),
    ],
    "huggingface": [
        # Local sentence-transformers — api_key only needed for gated models.
        ("api_key", True),
    ],
    # Managed path. AICORE_* creds live in .env (bootstrap of gen_ai_hub SDK),
    # the doc just stores the deployment_id.
    "sap_aicore": [
        ("deployment_id", False),
    ],
}


def provider_fields(provider: str) -> list[tuple[str, bool]]:
    """Return ``[(field_name, is_sensitive), ...]`` for ``provider``. Empty if unknown."""
    return list(_PROVIDER_FIELDS.get(provider, []))


def known_providers() -> list[str]:
    """All providers the registry knows about. Used for SPA dropdowns + validation."""
    return sorted(_PROVIDER_FIELDS.keys())


def is_sensitive(provider: str, field_name: str) -> bool:
    """Lookup helper. False if the provider/field is unknown — caller decides."""
    for fname, sensitive in _PROVIDER_FIELDS.get(provider, []):
        if fname == field_name:
            return sensitive
    return False


# ─────────────────────────────────────────────────────────────────────────────
# DB provider registry — separate plane (2026-07 DB-config migration).
#
# The DB-config plane lives in the SAME ``ask-system-settings-v1`` index under
# targets ``db_dev`` / ``db_prod`` but needs its OWN registry: several ids
# (``databricks``) exist in BOTH the LLM registry above and here with different
# fields, so one dict keyed by provider name would collide.
#
# Each entry is ``(field_name, is_sensitive, kind)`` where ``kind`` ∈
# {"str", "int", "bool"}. The store keeps everything as strings (Fernet operates
# on strings; ``plain`` values are stringified on write); ``kind`` lets the read
# resolver coerce ``port`` back to int and ``secure``/``final`` back to bool so
# the DB adapters see native types.
#
# Field names + order MIRROR the setup SPA's Database form (the UI form owns the
# richer widget metadata — options, placeholders — that has no home in this
# registry). Keep the two in sync when adding a backend.
# ─────────────────────────────────────────────────────────────────────────────
_DB_PROVIDER_FIELDS: dict[str, list[tuple[str, bool, str]]] = {
    "postgresql": [
        ("host", False, "str"),
        ("port", False, "int"),
        ("database", False, "str"),
        ("user", False, "str"),
        ("password", True, "str"),
        ("sslmode", False, "str"),
    ],
    "hana": [
        ("host", False, "str"),
        ("port", False, "int"),
        ("user", False, "str"),
        ("password", True, "str"),
        ("schema", False, "str"),
    ],
    "snowflake": [
        ("account", False, "str"),
        ("user", False, "str"),
        ("password", True, "str"),
        ("private_key_file", False, "str"),  # a filesystem path, not the key material
        ("warehouse", False, "str"),
        ("database", False, "str"),
        ("schema", False, "str"),
        ("role", False, "str"),
    ],
    "databricks": [
        ("server_hostname", False, "str"),
        ("http_path", False, "str"),
        ("access_token", True, "str"),
        ("catalog", False, "str"),
        ("schema", False, "str"),
    ],
    "clickhouse": [
        ("host", False, "str"),
        ("port", False, "int"),
        ("username", False, "str"),
        ("password", True, "str"),
        ("database", False, "str"),
        ("secure", False, "bool"),
        ("final", False, "bool"),
    ],
    "sqlserver": [
        ("host", False, "str"),
        ("port", False, "int"),
        ("database", False, "str"),
        ("user", False, "str"),
        ("password", True, "str"),
        ("driver", False, "str"),
        ("encrypt", False, "str"),
        ("trust_server_certificate", False, "str"),
    ],
    "db2": [
        ("host", False, "str"),
        ("port", False, "int"),
        ("database", False, "str"),
        ("user", False, "str"),
        ("password", True, "str"),
        ("security", False, "str"),
    ],
    "bigquery": [
        ("project", False, "str"),
        ("credentials_path", False, "str"),  # ADC path, not the key material
        ("credentials_json", True, "str"),  # service-account JSON content (encrypted)
        ("dataset", False, "str"),
        ("location", False, "str"),
        ("maximum_bytes_billed", False, "str"),
    ],
    "fabric": [
        ("server", False, "str"),
        ("database", False, "str"),
        ("tenant_id", False, "str"),
        ("client_id", False, "str"),
        ("client_secret", True, "str"),
        ("driver", False, "str"),
    ],
}


def db_provider_fields(db_type: str) -> list[tuple[str, bool, str]]:
    """Return ``[(field_name, is_sensitive, kind), ...]`` for ``db_type``. Empty if unknown."""
    return list(_DB_PROVIDER_FIELDS.get(db_type, []))


def known_db_types() -> list[str]:
    """All DB backends the registry knows about."""
    return sorted(_DB_PROVIDER_FIELDS.keys())
