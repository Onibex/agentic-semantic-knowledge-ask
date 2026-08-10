"""Errors raised by SQL Executor."""

from __future__ import annotations


class SqlExecutorError(Exception):
    """Base error."""


class UnsupportedDbTypeError(SqlExecutorError):
    """Raised when the requested db_type has no registered adapter."""


class SqlExecutionError(SqlExecutorError):
    """Wraps the underlying driver exception (HANA / Postgres) so callers can react uniformly."""
