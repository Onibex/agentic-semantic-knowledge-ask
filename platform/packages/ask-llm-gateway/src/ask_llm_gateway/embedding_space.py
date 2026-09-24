# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The size of the vectors the search index stores.

One value decides it for the whole deployment: ``OPENSEARCH_EMBEDDING_DIM``, or
1024 when unset (Bedrock Titan Text Embeddings V2, the platform standard). The
registry indices are created with it, the embedder asks the model for exactly
that many dimensions, and ASK Setup shows it next to the embedder. Reading it
here, and only here, is what keeps the three from disagreeing.

The mapping of an OpenSearch index is immutable once created, so changing the
value means dropping the registry indices and publishing again.
"""

from __future__ import annotations

import os

EMBEDDING_DIM_ENV = "OPENSEARCH_EMBEDDING_DIM"
DEFAULT_EMBEDDING_DIM = 1024


def index_embedding_dim() -> int:
    """Return the vector size of the search index.

    A value that is not an integer raises instead of falling back to the
    default: an index built with one size and an embedder asked for another is
    a failure that only shows up at the first search.
    """
    raw = os.getenv(EMBEDDING_DIM_ENV)
    return int(raw) if raw else DEFAULT_EMBEDDING_DIM
