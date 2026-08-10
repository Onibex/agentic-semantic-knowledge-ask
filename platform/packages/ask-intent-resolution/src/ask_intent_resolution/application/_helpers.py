"""
Shared internal helpers for the 3 mode strategies (Iter 8.10).

`_load_settings` and `_trace` were duplicated in flash/precise/smart. Hoisted
here so the modes do not need to import each other (mode isolation is
enforced by the import-linter `mode-isolation` contract).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..domain.errors import StrategyExecutionError
from ..domain.result import ResolutionTrace


def _load_settings() -> dict:
    """Load `config/settings.json` from the current working directory.

    Each strategy needs runtime config (db creds, deployment ids) at first
    invocation. Strategies are typically built lazily inside FastAPI workers
    that start in the project root.
    """
    cfg_path = Path("config/settings.json")
    if not cfg_path.exists():
        raise StrategyExecutionError(
            "config/settings.json not found — strategy must run from project root"
        )
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _trace(
    started: float,
    strategy: str,
    *,
    notes: str | None = None,
) -> ResolutionTrace:
    """Build a `ResolutionTrace` with the elapsed wall-clock duration."""
    return ResolutionTrace(
        strategy=strategy,
        duration_ms=int((time.monotonic() - started) * 1000),
        notes=notes,
    )
