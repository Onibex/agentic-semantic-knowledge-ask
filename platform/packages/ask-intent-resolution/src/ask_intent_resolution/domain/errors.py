"""Errors raised by the Intent Resolution domain."""

from __future__ import annotations


class IntentResolutionError(Exception):
    """Base error for any Intent Resolution failure."""


class StrategyNotImplementedError(IntentResolutionError):
    """Raised when a request mode has no registered strategy."""


class StrategyExecutionError(IntentResolutionError):
    """Raised when a strategy fails to produce a valid IntentResolutionResult."""
