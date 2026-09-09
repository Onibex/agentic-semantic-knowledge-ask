# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Deployment-level resolution of the semantic layer's authoring language.

Lives in ``infrastructure`` (not ``domain``): it reads the environment, which
is I/O. The pure vocabulary (:class:`SemanticLanguage`) and the prompt
directives stay in ``domain.language``. Mirrors ``naming_config`` deliberately,
one flag shape for both deployment-level authoring decisions.

Resolution order (first hit wins):

1. ``ASK_SEMANTIC_LANGUAGE`` env var, the deployment switch.
2. ``semantic_layer.language`` in the caller-supplied config dict, when one is
   given.
3. :attr:`SemanticLanguage.EN`, the historical behavior, so every existing
   deployment keeps working with no config change.

The CWD-relative ``config/settings.json`` read is gone, for the reasons written
out in ``naming_config``: a deployment flag comes from the deployment, and an
ambient file is a source no test can isolate itself from.

An unrecognized value RAISES instead of silently defaulting: authoring a corpus
in the wrong language is only discovered as *degraded retrieval*, never as an
error, and re-authoring means re-enriching + re-publishing everything. Same
reasoning as the column-naming resolver, and the same practical rule, decide it
before authoring the corpus.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..domain.language import SemanticLanguage

logger = logging.getLogger(__name__)

_ENV_VAR = "ASK_SEMANTIC_LANGUAGE"


def resolve_semantic_language(config: dict[str, Any] | None = None) -> SemanticLanguage:
    """The deployment's :class:`SemanticLanguage` (env > caller config > English)."""
    raw = (os.getenv(_ENV_VAR) or "").strip().lower()
    source = f"env {_ENV_VAR}"
    if not raw:
        settings = config if isinstance(config, dict) else {}
        section = settings.get("semantic_layer")
        raw = str((section or {}).get("language") or "").strip().lower()
        source = "caller config semantic_layer.language"
    if not raw:
        return SemanticLanguage.EN
    try:
        return SemanticLanguage(raw)
    except ValueError:
        valid = ", ".join(m.value for m in SemanticLanguage)
        raise ValueError(
            f"Invalid semantic language {raw!r} (from {source}); expected one of: {valid}. "
            "Refusing to default silently — this decides the language the corpus is "
            "authored in AND the language retrieval queries are expressed in; a mismatch "
            "degrades retrieval without ever raising an error."
        ) from None
