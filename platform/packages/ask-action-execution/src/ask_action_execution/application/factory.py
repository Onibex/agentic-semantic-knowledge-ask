"""
Default-construction helper for the action execution service.

Reads ``config/settings.json``, builds the LLM-backed extractor, the MCP
adapter (when ``sap_s4hana.mcp_url`` is configured — otherwise None), and
wires both into the application service. The orchestrator's ``query.py``
calls ``build_default_action_service()`` on first use.
"""

from __future__ import annotations

import json
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
    s4 = cfg.get("sap_s4hana") or {}
    mcp_url = (s4.get("mcp_url") or "").strip()
    if not mcp_url:
        return None
    if not mcp_url.startswith("http"):
        mcp_url = f"http://{mcp_url}"
    return SapMcpAdapter(mcp_url)


def _load_config() -> dict[str, Any]:
    cfg_path = Path("config/settings.json")
    if not cfg_path.exists():
        raise RuntimeError("config/settings.json not found — service must run from project root")
    return json.loads(cfg_path.read_text(encoding="utf-8"))
