# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""One ledger for every environment variable this package writes.

Provider credentials reach LiteLLM and boto3 through ``os.environ``, and the
process is long-lived: the same worker serves a request with Bedrock active and,
after an admin edits the config, the next one with Anthropic. Writing on each
build is not enough — what the *previous* configuration wrote has to go, or it
outlives the configuration that put it there.

That outliving is not cosmetic. A stored Bedrock config holding only
``AWS_BEARER_TOKEN_BEDROCK`` cannot dislodge an ``AWS_ACCESS_KEY_ID`` an earlier
config (or a ``/test`` probe) left behind, and boto3 stops at the first
credential source it finds — so the call fails with "partial credentials", or
worse, succeeds against a key the admin believed they had removed.

Two rules make retirement safe:

**Scopes own names.** The live LLM, the embedder and the ``/test`` probe write
independently; a name is retired only when no scope claims it any more.
Switching the LLM to Anthropic must not strip the AWS variables a Bedrock
*embedder* still needs.

**Ambient values are restored, not erased.** A variable already in the
environment — a Kyma Secret, a shell export, ``env_file`` — is remembered before
the first overwrite and put back when the ledger lets go. This package borrows
the environment; it does not own it.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping

_LOCK = threading.Lock()

# scope -> the env var names that scope currently contributes.
_OWNED: dict[str, set[str]] = {}

# name -> the value it held before this package first overwrote it (None = unset).
# Only holds names that at least one scope owns; dropped on retirement.
_AMBIENT: dict[str, str | None] = {}


def apply(scope: str, values: Mapping[str, str]) -> list[str]:
    """Make ``scope``'s contribution to ``os.environ`` exactly ``values``.

    Writes every entry, then retires the names ``scope`` wrote last time and no
    longer writes — unless another scope still claims them. Empty values are
    ignored rather than written, so a blank field never clobbers a real one.

    Returns the names written, in the order given.
    """
    pending = {str(k): str(v) for k, v in values.items() if k and v}

    with _LOCK:
        for name, value in pending.items():
            if name not in _AMBIENT:
                _AMBIENT[name] = os.environ.get(name)
            os.environ[name] = value

        previous = _OWNED.get(scope, set())
        _OWNED[scope] = set(pending)

        stale = previous - set(pending)
        if stale:
            claimed: set[str] = set()
            for other, owned in _OWNED.items():
                if other != scope:
                    claimed |= owned
            for name in stale - claimed:
                ambient = _AMBIENT.pop(name, None)
                if ambient is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = ambient

    return list(pending)


def release(scope: str) -> None:
    """Drop ``scope`` entirely, retiring whatever only it claimed."""
    apply(scope, {})


def owned_by(scope: str) -> set[str]:
    """The names ``scope`` currently contributes — for tests and diagnostics."""
    with _LOCK:
        return set(_OWNED.get(scope, set()))


def reset() -> None:
    """Forget every scope without touching ``os.environ`` — tests only."""
    with _LOCK:
        _OWNED.clear()
        _AMBIENT.clear()
