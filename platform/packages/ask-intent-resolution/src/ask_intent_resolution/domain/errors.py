# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Errors raised by the Intent Resolution domain."""

from __future__ import annotations


class IntentResolutionError(Exception):
    """Base error for any Intent Resolution failure."""


class StrategyNotImplementedError(IntentResolutionError):
    """Raised when a request mode has no registered strategy."""


class StrategyExecutionError(IntentResolutionError):
    """Raised when a strategy fails to produce a valid IntentResolutionResult."""
