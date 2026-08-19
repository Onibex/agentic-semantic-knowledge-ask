# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

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
