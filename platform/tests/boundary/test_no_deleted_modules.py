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
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


_FORBIDDEN_IMPORTS = ("utils.yaml_data_product",)

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
    )
    survivors = [p for p in deleted_paths if (REPO_ROOT / p).exists()]
    assert survivors == [], (
        "These files were supposed to be deleted by the Knowledge refactor "
        "but still exist:\n" + "\n".join(f"  {p}" for p in survivors)
    )
