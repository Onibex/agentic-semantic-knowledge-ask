"""Errors raised by the Schema Service."""

from __future__ import annotations


class SchemaServiceError(Exception):
    """Base error."""


class EntityNotFoundError(SchemaServiceError):
    """Raised when no entity matches the query (schema retriever returned 0 hits)."""
