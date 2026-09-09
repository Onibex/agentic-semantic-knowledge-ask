# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Default-construction helper for the action execution service.

Reads ``config/settings.json``, builds the LLM-backed extractor, the MCP
adapter (when ``sap_s4hana.mcp_url`` is configured — otherwise None), and
wires both into the application service. The orchestrator's ``query.py``
calls ``build_default_action_service()`` on first use.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..infrastructure.sap_mcp_adapter import SapMcpAdapter
from .action_extractor import LlmActionExtractor
from .service import ActionExecutionApplicationService


def build_default_action_service() -> ActionExecutionApplicationService:
    """Construct an ``ActionExecutionApplicationService`` ready to handle
    ACTION_EXECUTION intents.

    The MCP adapter is optional: if no ``sap_s4hana.mcp_url`` is set, the
    service still constructs but every request returns the
    "SAP S/4HANA is not configured" answer.
    """
    from ask_llm_gateway.application.factory import build_llm

    cfg = _load_config()
    llm = build_llm(cfg)
    # Build adapter first so the extractor can discover live MCP tools.
    adapter = _build_adapter(cfg)
    extractor = LlmActionExtractor(llm=llm, adapter=adapter)
    return ActionExecutionApplicationService(extractor=extractor, adapter=adapter, llm=llm)


def _build_adapter(cfg: dict[str, Any]) -> SapMcpAdapter | None:
    """The MCP adapter, or None when no ``mcp_url`` is configured.

    Reads the encrypted store, not ``cfg``: the SAP section moved there so the
    password would stop living in cleartext on a shared volume. ``cfg`` is still
    taken so the signature stays stable for the LLM half of the factory.

    Note this failure is INVISIBLE: no screen reports a missing adapter, chat
    just quietly loses action execution. Hence the explicit log line.
    """
    from ask_llm_gateway.infrastructure.secrets import resolve_sap_config

    mcp_url = str(resolve_sap_config().get("mcp_url") or "").strip()
    if not mcp_url:
        logging.getLogger(__name__).info(
            "No mcp_url configured; action execution runs without an MCP adapter"
        )
        return None
    if not mcp_url.startswith("http"):
        mcp_url = f"http://{mcp_url}"
    return SapMcpAdapter(mcp_url)


def _load_config() -> dict[str, Any]:
    """Read ``config/settings.json``; ``{}`` when absent or unreadable.

    Never raises: the file is gitignored (a fresh clone has none) and env vars
    carry every key that matters, so absence must degrade, not crash a request
    path (BACKLOG group 0, P1 — hit live 2026-08-12). With ``{}`` the MCP
    adapter is simply not configured, which this factory already handles."""
    cfg_path = Path("config/settings.json")
    if not cfg_path.exists():
        logging.getLogger(__name__).warning(
            "config/settings.json not found (resolved=%s, cwd=%s) — using environment only",
            cfg_path.resolve(),
            os.getcwd(),
        )
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a broken file must not take the service down
        logging.getLogger(__name__).warning(
            "config/settings.json is not valid JSON — ignoring it"
        )
        return {}
    return data if isinstance(data, dict) else {}
