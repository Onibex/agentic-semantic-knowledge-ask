# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Environment-aware OpenSearch index naming (UX_CHANGES audit CH-2, Iter 2).

The semantic layer is published per environment (`dev` / `prod`) into separate
OpenSearch indices on the SAME cluster (audit Q5/Q6). The naming convention is
``{base}-{env}`` — e.g. ``ask-entity-registry-v1`` + ``dev`` →
``ask-entity-registry-v1-dev``.

This is the SINGLE canonical resolver. The Knowledge Graph package owns every
ASK index name, so both the write path (admin-api publish) and — once the read
cutover lands (Iter 4) — the orchestrator read path resolve names through here.

Backward-compatibility shim (Iter 2): ``env=None`` (or empty) returns the base
name UNCHANGED. This keeps the currently-running, un-suffixed indices working
while the env-publish capability is introduced additively. Iter 4 flips the
default flow + the orchestrator reads to a concrete env and drops the shim.
"""

from __future__ import annotations

from typing import Literal

Environment = Literal["dev", "prod"]

# The two environments are hardcoded (audit Q6 — exactly two, no global switcher).
ALL_ENVIRONMENTS: tuple[Environment, ...] = ("dev", "prod")


def is_valid_env(env: str | None) -> bool:
    """True for a recognised environment. ``None``/empty is NOT an env (it is
    the legacy/un-suffixed shim, handled separately)."""
    return env in ALL_ENVIRONMENTS


def normalize_env(env: str | None) -> str | None:
    """Lowercase + validate. ``None``/empty → ``None`` (unsuffixed shim).

    Raises ``ValueError`` for any non-empty value that is not ``dev``/``prod`` —
    fail loud so a typo never silently writes to the wrong index.
    """
    if env is None:
        return None
    norm = env.strip().lower()
    if not norm:
        return None
    if norm not in ALL_ENVIRONMENTS:
        raise ValueError(f"Unknown environment {env!r} — expected one of {ALL_ENVIRONMENTS}.")
    return norm


def env_index(base: str, env: str | None) -> str:
    """Resolve a base index name to its env-suffixed form.

    ``env_index("ask-entity-registry-v1", "dev") == "ask-entity-registry-v1-dev"``
    ``env_index("ask-entity-registry-v1", None)  == "ask-entity-registry-v1"`` (shim)
    """
    norm = normalize_env(env)
    return base if norm is None else f"{base}-{norm}"
