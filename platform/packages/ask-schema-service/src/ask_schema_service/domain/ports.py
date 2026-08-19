# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Inbound port: SchemaService Protocol."""

from __future__ import annotations

from typing import Protocol

from .models import SchemaQuery, SchemaResponse


class SchemaService(Protocol):
    """The orchestrator-facing contract for SCHEMA_QUERY."""

    def answer(self, query: SchemaQuery) -> SchemaResponse: ...
