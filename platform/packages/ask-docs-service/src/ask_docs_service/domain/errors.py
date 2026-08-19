# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Errors raised by the Docs Service."""

from __future__ import annotations


class DocsServiceError(Exception):
    """Base error."""


class NoDocumentsFoundError(DocsServiceError):
    """Raised when retrieval returns 0 hits for a question."""


class RetrieverUnavailableError(DocsServiceError):
    """Raised when the underlying OpenSearch index is unreachable."""
