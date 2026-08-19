# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Errors raised by SQL Executor."""

from __future__ import annotations


class SqlExecutorError(Exception):
    """Base error."""


class UnsupportedDbTypeError(SqlExecutorError):
    """Raised when the requested db_type has no registered adapter."""


class SqlExecutionError(SqlExecutorError):
    """Wraps the underlying driver exception (HANA / Postgres) so callers can react uniformly."""
