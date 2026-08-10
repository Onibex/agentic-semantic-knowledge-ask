"""``GET /v1/admin/config`` and ``POST /v1/admin/config`` — read/write config/settings.json.

Rules
─────
* File is resolved relative to the process CWD (``Path("config/settings.json")``).
* GET masks sensitive fields before returning.
* POST performs a deep-merge (top-level keys not present in the payload are
  preserved).  Sensitive fields that arrive empty or as the mask sentinel
  ``"••••••••"`` (or any value starting with ``"••"``) are left unchanged on
  disk.
* Nested sections ``deployments`` and ``sap_ai_core`` are merged one level deep
  (individual sub-keys survive if not in the incoming payload).
* After a successful write the in-process singletons held by the
  ``dictionary``, ``embeddings``, and ``yaml_ingestion`` router modules are
  reset via ``importlib`` to avoid circular imports.
"""

from __future__ import annotations

import importlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin/config"])

# ── Config file path (CWD-relative) ─────────────────────────────────────────
_CONFIG_PATH = Path("config/settings.json")

# ── Sensitive field paths (dot-notation) ────────────────────────────────────
_SENSITIVE_PATHS: list[tuple[str, ...]] = [
    ("hana", "password"),
    ("postgresql", "password"),
    ("opensearch", "password"),
    ("ias", "client_secret"),
    ("sap_s4hana", "password"),
]

# ── Mask sentinel ────────────────────────────────────────────────────────────
_MASK = "••••••••"


# ── Pydantic models ──────────────────────────────────────────────────────────
from pydantic import BaseModel  # noqa: E402  (after stdlib imports is fine)


class ConfigResponse(BaseModel):
    config: dict[str, Any]


class ConfigSaveRequest(BaseModel):
    config: dict[str, Any]


class ConfigSaveResponse(BaseModel):
    success: bool
    cleared: list[str] = []
    message: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_raw() -> dict[str, Any]:
    """Return the raw (unmasked) config dict, or {} if the file doesn't exist."""
    if not _CONFIG_PATH.exists():
        return {}
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _mask_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-copied config dict with sensitive fields replaced by the mask."""
    import copy

    masked = copy.deepcopy(cfg)
    for path in _SENSITIVE_PATHS:
        node = masked
        for key in path[:-1]:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict) and path[-1] in node and node[path[-1]]:
            node[path[-1]] = _MASK
    return masked


def _is_masked(value: Any) -> bool:
    """Return True if *value* is the sentinel mask or starts with ``••``."""
    if not isinstance(value, str):
        return False
    return value.startswith("••")


def _merge_config(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge *incoming* into *existing* and return the result.

    * Top-level keys absent from *incoming* are kept from *existing*.
    * For the special nested sections ``deployments`` and ``sap_ai_core`` a
      one-level deep merge is performed so individual sub-keys survive.
    * For every other key the incoming value wins (shallow replace).
    * Sensitive fields that arrive masked are restored from *existing*.
    """
    import copy

    result = copy.deepcopy(existing)

    _ONE_LEVEL_DEEP_MERGE_KEYS = {"deployments", "sap_ai_core", "sap_s4hana"}

    for top_key, top_val in incoming.items():
        if top_key in _ONE_LEVEL_DEEP_MERGE_KEYS and isinstance(top_val, dict):
            existing_sub = result.get(top_key, {})
            if isinstance(existing_sub, dict):
                merged_sub = {**existing_sub, **top_val}
                result[top_key] = merged_sub
            else:
                result[top_key] = top_val
        else:
            result[top_key] = top_val

    # Restore masked sensitive fields from the existing config
    for path in _SENSITIVE_PATHS:
        node_result = result
        node_existing = existing
        for key in path[:-1]:
            if not isinstance(node_result, dict) or key not in node_result:
                node_result = None
                break
            node_result = node_result[key]
            node_existing = node_existing.get(key, {}) if isinstance(node_existing, dict) else {}

        leaf = path[-1]
        if isinstance(node_result, dict) and leaf in node_result:
            incoming_val = node_result[leaf]
            if _is_masked(incoming_val):
                # Restore from existing
                existing_val = (
                    node_existing.get(leaf, "") if isinstance(node_existing, dict) else ""
                )
                node_result[leaf] = existing_val

    return result


def _reset_router_singletons() -> list[str]:
    """Reset cached singletons in sibling router modules without circular imports."""
    cleared: list[str] = []
    targets = [
        "ask_admin_api.routers.dictionary",
        "ask_admin_api.routers.embeddings",
        "ask_admin_api.routers.yaml_ingestion",
    ]
    for module_path in targets:
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, "reset_singletons"):
                names = mod.reset_singletons()
                cleared.extend(names)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reset_singletons failed for %s: %s", module_path, exc)
    return cleared


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/config",
    response_model=ConfigResponse,
    summary="Read settings.json (sensitive fields masked)",
    description=(
        "Returns the content of ``config/settings.json`` relative to the "
        "process CWD.  Sensitive fields (passwords, client_secret) are "
        "replaced with ``••••••••``.  Returns an empty dict if the file "
        "does not yet exist."
    ),
)
async def get_config(
    claims: TokenClaims = Depends(validate_token),
) -> ConfigResponse:
    trace_id = uuid.uuid4().hex
    auth_email = getattr(claims, "email", "unknown")
    logger.info("[%s] GET /v1/admin/config user=%s", trace_id, auth_email)

    raw = _read_raw()
    masked = _mask_config(raw)
    return ConfigResponse(config=masked)


@router.post(
    "/config",
    response_model=ConfigSaveResponse,
    summary="Merge and save settings.json",
    description=(
        "Merges the supplied partial config into the existing "
        "``config/settings.json``.  Keys absent from the payload are "
        "preserved.  Masked sensitive values are not overwritten.  "
        "After writing, in-process singletons (dictionary, embeddings, "
        "yaml_ingestion) are reset so the next request picks up the new "
        "settings."
    ),
)
async def save_config(
    body: ConfigSaveRequest,
    claims: TokenClaims = Depends(validate_token),
) -> ConfigSaveResponse:
    trace_id = uuid.uuid4().hex
    auth_email = getattr(claims, "email", "unknown")
    logger.info(
        "[%s] POST /v1/admin/config user=%s keys=%s", trace_id, auth_email, list(body.config.keys())
    )

    existing = _read_raw()
    merged = _merge_config(existing, body.config)

    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("[%s] settings.json written successfully", trace_id)

    cleared = _reset_router_singletons()
    logger.info("[%s] singletons reset: %s", trace_id, cleared)

    return ConfigSaveResponse(
        success=True,
        cleared=cleared,
        message="Configuration saved.",
    )
