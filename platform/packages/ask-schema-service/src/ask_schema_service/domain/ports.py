"""Inbound port: SchemaService Protocol."""

from __future__ import annotations

from typing import Protocol

from .models import SchemaQuery, SchemaResponse


class SchemaService(Protocol):
    """The orchestrator-facing contract for SCHEMA_QUERY."""

    def answer(self, query: SchemaQuery) -> SchemaResponse: ...
