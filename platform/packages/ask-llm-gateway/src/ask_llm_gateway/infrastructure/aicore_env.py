# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Shared helper that exports SAP AI Core credentials to ``os.environ`` from a
parsed aicore service-key dict.

The gen_ai_hub SDK boots its proxy client via ``AICoreV2Client.from_env()``,
which expects ``AICORE_BASE_URL``, ``AICORE_AUTH_URL``, ``AICORE_CLIENT_ID``,
``AICORE_CLIENT_SECRET`` and ``AICORE_RESOURCE_GROUP`` to already live in the
process environment. In Kyma those vars are injected from a Secret; in dev
they live in ``.env``; either way the JSON service key on disk
(``config/aicore_config.json``) is the authoritative source — both the
embedder and the chat-LLM factory now route through this helper so a missing
``.env`` (e.g. fresh uvicorn process) cannot leave the SDK uninitialised.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def export_aicore_env(aicore_config: dict) -> None:
    """Mirror the 5 ``AICORE_*`` env vars from a parsed service-key dict."""
    os.environ["AICORE_AUTH_URL"] = aicore_config.get("url", "")
    os.environ["AICORE_CLIENT_ID"] = aicore_config.get("clientid", "")
    os.environ["AICORE_CLIENT_SECRET"] = aicore_config.get("clientsecret", "")
    os.environ["AICORE_BASE_URL"] = aicore_config.get("serviceurls", {}).get("AI_API_URL", "")
    os.environ.setdefault("AICORE_RESOURCE_GROUP", "default")


def write_aicore_service_key_file(aicore_config: dict) -> str:
    """Persist the service-key JSON to a temp file and export its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(aicore_config, tmp)
    tmp.flush()
    tmp.close()
    os.environ["AICORE_SERVICE_KEY_FILE"] = tmp.name
    return tmp.name


def load_aicore_config_from_settings(settings: dict) -> dict | None:
    """Resolve ``settings["sap_ai_core"]["config_path"]`` and parse the JSON.

    Returns ``None`` if the path key is missing or the file cannot be read —
    callers should treat that as "fall back to whatever is already in
    ``os.environ``" (Kyma path).

    Path-style normalisation: ``settings.json`` may have been written from a
    Windows host (1_Setup.py) which serialises ``Path("config/aicore_config.json")``
    as ``"config\\\\aicore_config.json"``. On Linux that backslash becomes part
    of the filename and the file is "missing". We replace backslashes with
    forward slashes before resolving so both styles work everywhere.
    """
    path = (settings.get("sap_ai_core") or {}).get("config_path")
    if not path:
        return None
    p = Path(str(path).replace("\\", "/"))
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def ensure_aicore_env_from_settings(settings: dict) -> bool:
    """Convenience: load the aicore JSON pointed to by ``settings`` and export.

    Returns True if env vars were set from the JSON, False if no JSON was
    available (caller should rely on pre-existing env / Kyma Secret).
    """
    cfg = load_aicore_config_from_settings(settings)
    if cfg is None:
        return False
    export_aicore_env(cfg)
    return True
