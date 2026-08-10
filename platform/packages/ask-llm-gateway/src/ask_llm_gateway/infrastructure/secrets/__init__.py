"""Encrypted secrets backend (Fernet + OpenSearch).

Public surface:
  * ``crypto.encrypt`` / ``crypto.decrypt`` — Fernet round-trip with fail-closed boot.
  * ``registry.provider_fields`` — per-provider field metadata (sensitive vs plain).
  * ``repository.SecretsRepository`` — OpenSearch CRUD on ``ask-system-settings-v1``.
  * ``provider.SecretsProvider`` — runtime cache + ``export_to_env`` for the factory.

See ``docs/HANDOFF_encrypted_secrets_opensearch.md`` for the design.
"""

from .crypto import ENCRYPTION_KEY_ENV, decrypt, encrypt
from .db_config import is_db_configured, resolve_db_config
from .provider import SecretsProvider, export_fields_to_env, get_secrets_provider
from .registry import db_provider_fields, known_db_types, provider_fields
from .repository import (
    ACTIVE_POINTER_ID,
    CONN_PREFIX,
    INDEX_SYSTEM_SETTINGS,
    LLM_ACTIVE_POINTER_ID,
    LLM_CONN_PREFIX,
    SecretsRepository,
    new_connection_id,
    new_llm_connection_id,
)

__all__ = [
    "ACTIVE_POINTER_ID",
    "CONN_PREFIX",
    "ENCRYPTION_KEY_ENV",
    "INDEX_SYSTEM_SETTINGS",
    "LLM_ACTIVE_POINTER_ID",
    "LLM_CONN_PREFIX",
    "SecretsProvider",
    "SecretsRepository",
    "db_provider_fields",
    "decrypt",
    "encrypt",
    "export_fields_to_env",
    "get_secrets_provider",
    "is_db_configured",
    "known_db_types",
    "new_connection_id",
    "new_llm_connection_id",
    "provider_fields",
    "resolve_db_config",
]
