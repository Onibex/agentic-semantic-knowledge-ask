"""Errors raised by the Knowledge Graph package (read + write)."""

from __future__ import annotations


class KnowledgeGraphError(Exception):
    """Base error."""


class EntityNotFoundError(KnowledgeGraphError):
    """Raised when get_entity_by_id finds nothing."""


class IndexUnavailableError(KnowledgeGraphError):
    """Raised when the underlying OpenSearch index is missing or unreachable."""


# Iter 6 — write side
class IngestionError(KnowledgeGraphError):
    """Raised when an ingestion attempt fails (parse error, index write error, etc.)."""


class UnsupportedLayerError(KnowledgeGraphError):
    """Raised when a YAML's `layer` value is not bronze/silver/gold."""


# Iter 8 — dictionary side
class DictionaryError(KnowledgeGraphError):
    """Raised when a semantic-dictionary read or write fails at the adapter boundary."""
