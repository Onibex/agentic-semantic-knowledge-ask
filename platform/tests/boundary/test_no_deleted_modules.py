# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Boundary check: no module may import symbols that were physically removed
during refactors. Each entry below documents what was removed, why it was
removed, and where the replacement lives. Adding to this list is cheap; it
keeps drift detectable without coupling the test to specific replacement
paths.

Current entries
───────────────
- ``utils.yaml_data_product`` — moved to
  ``ask_knowledge_graph.application.rag_text_renderer`` during the
  Knowledge refactor. The new home parses ASK Spec YAMLs directly (no
  more bespoke ``data_product/db_table_name`` schema).
- The SAP AI Core route through SAP's own SDK: ``chat_llm_factory``,
  ``embedder_factory``, ``chat_llm``, ``embedder`` and ``aicore_env`` in
  ``ask_llm_gateway``, the ``llm_config`` router in ``ask_admin_api``, and
  ``gen_ai_hub`` itself. SAP AI Core is a LiteLLM provider now (``sap``),
  built by ``ask_llm_gateway.application.factory`` like every other one, and
  the SDK is no longer a dependency: importing it again is a decision, not a
  drift.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


_FORBIDDEN_IMPORTS = (
    "utils.yaml_data_product",
    "ask_llm_gateway.application.chat_llm_factory",
    "ask_llm_gateway.application.embedder_factory",
    "ask_llm_gateway.infrastructure.chat_llm",
    "ask_llm_gateway.infrastructure.embedder",
    "ask_llm_gateway.infrastructure.aicore_env",
    "ask_admin_api.routers.llm_config",
    "gen_ai_hub",
)

_SCAN_DIRS = (
    "deploy",
    "packages",
    "tests",
)


def _build_pattern() -> re.Pattern[str]:
    alt = "|".join(re.escape(m) for m in _FORBIDDEN_IMPORTS)
    return re.compile(
        rf"^(?:from|import)\s+(?P<mod>{alt})(?:\.|\s|$)",
        re.MULTILINE,
    )


_PATTERN = _build_pattern()


def _scan(dir_path: Path) -> list[tuple[Path, int, str, str]]:
    hits: list[tuple[Path, int, str, str]] = []
    for py in dir_path.rglob("*.py"):
        if py.resolve() == Path(__file__).resolve():
            continue
        text = py.read_text(encoding="utf-8")
        for match in _PATTERN.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.start())
            line_text = text[match.start() : line_end if line_end != -1 else len(text)]
            hits.append((py, line_no, line_text, match.group("mod")))
    return hits


def test_no_imports_of_deleted_modules():
    all_hits: list[tuple[Path, int, str, str]] = []
    for d in _SCAN_DIRS:
        target = REPO_ROOT / d
        if target.is_dir():
            all_hits.extend(_scan(target))
    assert all_hits == [], (
        "The following modules were physically deleted; their imports must "
        "go through the new home. See test docstring for the migration "
        "table.\nViolations:\n"
        + "\n".join(f"  {p.relative_to(REPO_ROOT)}:{n}: {t}" for (p, n, t, _m) in all_hits)
    )


def test_deleted_module_files_are_actually_gone():
    """Sanity: if any of the source paths reappears, this guard becomes
    meaningless. Fail loud so the rename gets handled deliberately."""
    deleted_paths = (
        "utils/yaml_data_product.py",
        "packages/ask-intent-resolution/src/ask_intent_resolution/flash/infrastructure/opensearch_vectorstore.py",
        "packages/ask-llm-gateway/src/ask_llm_gateway/application/chat_llm_factory.py",
        "packages/ask-llm-gateway/src/ask_llm_gateway/application/embedder_factory.py",
        "packages/ask-llm-gateway/src/ask_llm_gateway/infrastructure/chat_llm.py",
        "packages/ask-llm-gateway/src/ask_llm_gateway/infrastructure/embedder.py",
        "packages/ask-llm-gateway/src/ask_llm_gateway/infrastructure/aicore_env.py",
        "packages/ask-admin-api/src/ask_admin_api/routers/llm_config.py",
    )
    survivors = [p for p in deleted_paths if (REPO_ROOT / p).exists()]
    assert survivors == [], (
        "These files were deleted on purpose (see the module docstring) "
        "but exist again:\n" + "\n".join(f"  {p}" for p in survivors)
    )
