# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Structured logging configuration for ask-admin-api.

Wires structlog as the backend for the stdlib ``logging`` module so every
existing ``logger.info(...)`` call across the codebase becomes JSON output
without touching the call sites.

Output format is selectable at startup:
  * ``LOG_FORMAT=json``   → newline-delimited JSON (default in production)
  * ``LOG_FORMAT=console`` → pretty colored output (default in dev)

Log level via ``LOG_LEVEL`` env var (default ``INFO``).

Usage — call once at process start (FastAPI lifespan / main entry)::

    from .logging_config import configure_logging
    configure_logging()
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def _resolve_format() -> str:
    fmt = (os.getenv("LOG_FORMAT") or "").lower().strip()
    if fmt in {"json", "console"}:
        return fmt
    # Default heuristic: console when stdout is a TTY (developer machine),
    # JSON otherwise (containers, CI, prod).
    return "console" if sys.stdout.isatty() else "json"


def _resolve_level() -> int:
    name = (os.getenv("LOG_LEVEL") or "INFO").upper().strip()
    return getattr(logging, name, logging.INFO)


def configure_logging() -> None:
    """Wire structlog + stdlib logging.

    Idempotent — safe to call multiple times (re-configures cleanly).
    """
    fmt = _resolve_format()
    level = _resolve_level()
    json_logs = fmt == "json"

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        # Pull `extra={...}` kwargs from stdlib calls into the event_dict so
        # `logger.info("msg", extra={"k": v})` ends up with k=v in JSON output.
        structlog.stdlib.ExtraAdder(),
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if json_logs:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    # Replace handlers idempotently — avoid stacking on reload.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)

    # Tone down chatty third-party loggers in production. Keep them at INFO
    # in development so problems are visible.
    if json_logs:
        for noisy in (
            "uvicorn.access",
            "httpx",
            "httpcore",
            "opensearch",
            "urllib3",
            "asyncio",
        ):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Convenience accessor for new call sites that want structured kwargs.

    Existing call sites using ``logging.getLogger(__name__)`` continue to
    work unchanged — they go through the same pipeline because the root
    handler is the structlog ProcessorFormatter.
    """
    return structlog.get_logger(name)
