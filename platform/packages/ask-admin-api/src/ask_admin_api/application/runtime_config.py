# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""One tolerant home for reading ``config/settings.json``.

Why this module exists (BACKLOG group 0, P1 — hit live 2026-08-12): the file is
gitignored, so a fresh clone has only ``settings.example.json``, and the platform
reported that absence as **two unrelated, undiagnosable failures**:

* ``GET /v1/admin/yaml/published-ids -> 500: 'NoneType' object has no attribute
  'get'`` — ``ConfigManager.load_config()`` returns ``None`` and callers did
  ``config.get("opensearch")`` on it.
* ``RuntimeError: config/settings.json not found — service must run from project
  root`` — the same missing file, from a different copy of the same helper, on
  business-domain publish.

The file is a MINIMAL fallback, not a requirement: env vars (``OPENSEARCH_*``,
``LLM_*``, ``EMBEDDER_*``) override every key that matters, and DB/LLM
credentials live encrypted in OpenSearch. So absence must degrade to ``{}`` with
one clear warning, never crash a request path — and it must be reported ONCE at
boot, where an operator can act on it, instead of endpoint by endpoint.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/settings.json")


def load_runtime_config(path: Path | None = None) -> dict[str, Any]:
    """Read ``config/settings.json``; return ``{}`` when absent or unreadable.

    Never raises. A malformed file is reported and treated as absent — a syntax
    error must not take a service down when env vars can carry it.
    """
    cfg_path = path or CONFIG_PATH
    if not cfg_path.exists():
        logger.warning(
            "config/settings.json not found (looked at %s, cwd=%s) — continuing with "
            "environment variables only. Copy config/settings.example.json to "
            "config/settings.json to silence this.",
            cfg_path.resolve(),
            os.getcwd(),
        )
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a broken file must not kill a request path
        logger.warning("config/settings.json is not valid JSON (%s) — ignoring it", cfg_path)
        return {}
    return data if isinstance(data, dict) else {}


def config_status(path: Path | None = None) -> dict[str, Any]:
    """Boot/health-facing description of the config file's state.

    Returned by ``GET /v1/health`` and logged at boot so a missing file is
    visible where it can be acted on, naming the RESOLVED path and the cwd —
    the two facts that make the "must run from project root" class of error
    obvious instead of mysterious.
    """
    cfg_path = path or CONFIG_PATH
    exists = cfg_path.exists()
    status: dict[str, Any] = {
        "path": str(cfg_path),
        "resolved_path": str(cfg_path.resolve()),
        "cwd": os.getcwd(),
        "present": exists,
        "parseable": False,
        "sections": [],
    }
    if not exists:
        return status
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return status
    if isinstance(data, dict):
        status["parseable"] = True
        status["sections"] = sorted(data.keys())
    return status


def log_config_status(path: Path | None = None) -> dict[str, Any]:
    """Log the config state once at boot. Returns the status for reuse."""
    status = config_status(path)
    if not status["present"]:
        logger.warning(
            "config/settings.json ABSENT (resolved=%s, cwd=%s) — running on environment "
            "variables only. Endpoints needing file config will use defaults.",
            status["resolved_path"],
            status["cwd"],
        )
    elif not status["parseable"]:
        logger.warning(
            "config/settings.json present but NOT parseable (resolved=%s) — ignored",
            status["resolved_path"],
        )
    else:
        logger.info(
            "config/settings.json loaded (resolved=%s, sections=%s)",
            status["resolved_path"],
            ", ".join(status["sections"]) or "none",
        )
    return status
