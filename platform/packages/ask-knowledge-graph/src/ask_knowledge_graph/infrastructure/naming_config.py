# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Deployment-level resolution of the curated column naming mode.

Lives in ``infrastructure`` (not ``domain``): it reads the environment, which
is I/O. The pure vocabulary (:class:`ColumnNamingMode`) stays in
``domain.naming``.

Resolution order (first hit wins):

1. ``ASK_COLUMN_NAMING`` env var, the deployment switch (precedent:
   ``SEMANTIC_LAYER_AUTO_INIT``).
2. ``ingestion.column_naming`` in the caller-supplied config dict, when one is
   given.
3. :attr:`ColumnNamingMode.TECHNICAL`, the historical behavior.

This resolver USED to read a CWD-relative ``config/settings.json`` when the
caller passed no dict. That read is gone: a deployment flag now comes from the
deployment, so a Kubernetes pod needs no shared mutable file to know how to
name a column. It also closes a whole class of test flakiness, because an
ambient settings file was a source no test could isolate itself from
(``monkeypatch.delenv`` drops the env var and leaves the file, which is how
this bit three times in one session, see BACKLOG group 0).

An unrecognized value RAISES instead of silently defaulting: a misconfigured
mode would mint physical column names that do not match the client's tables,
which is the exact failure this flag exists to prevent. The mode is fixed
before the first ingest of a deployment and never changed on a populated
corpus (see REQ_CURATED_COLUMN_NAMING.md).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..domain.naming import ColumnNamingMode

logger = logging.getLogger(__name__)

_ENV_VAR = "ASK_COLUMN_NAMING"


def resolve_column_naming_mode(config: dict[str, Any] | None = None) -> ColumnNamingMode:
    """The deployment's :class:`ColumnNamingMode` (env > caller config > technical)."""
    raw = (os.getenv(_ENV_VAR) or "").strip().lower()
    source = f"env {_ENV_VAR}"
    if not raw:
        settings = config if isinstance(config, dict) else {}
        ingestion = settings.get("ingestion")
        raw = str((ingestion or {}).get("column_naming") or "").strip().lower()
        source = "caller config ingestion.column_naming"
    if not raw:
        return ColumnNamingMode.TECHNICAL
    try:
        return ColumnNamingMode(raw)
    except ValueError:
        valid = ", ".join(m.value for m in ColumnNamingMode)
        raise ValueError(
            f"Invalid column naming mode {raw!r} (from {source}); expected one of: {valid}. "
            "Refusing to default silently — the mode decides the physical column names "
            "minted at ingest."
        ) from None
