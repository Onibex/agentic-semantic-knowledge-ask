"""Errors raised by SQL Generation."""

from __future__ import annotations


class SqlGenerationError(Exception):
    """Base error for any SQL Generation failure."""


class EmptyQuestionError(SqlGenerationError):
    """Raised when the request has no question."""


class NoYamlsError(SqlGenerationError):
    """Raised when no YAML schema context was supplied (Phases 2-3 produced nothing)."""


class LLMInvocationError(SqlGenerationError):
    """Raised when the LLM call (or its JSON parse) fails after retries."""
