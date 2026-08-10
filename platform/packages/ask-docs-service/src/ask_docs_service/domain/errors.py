"""Errors raised by the Docs Service."""

from __future__ import annotations


class DocsServiceError(Exception):
    """Base error."""


class NoDocumentsFoundError(DocsServiceError):
    """Raised when retrieval returns 0 hits for a question."""


class RetrieverUnavailableError(DocsServiceError):
    """Raised when the underlying OpenSearch index is unreachable."""
