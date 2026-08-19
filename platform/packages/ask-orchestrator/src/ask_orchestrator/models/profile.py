# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Request / response models for the ``/v1/profile`` endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProfileBuildRequest(BaseModel):
    """Inputs for one profile build. The UI hands the orchestrator the chat
    history it has already collected locally; the orchestrator runs the LLM."""

    user_id: str
    display_name: str = ""
    role: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)


class ProfileBuildResponse(BaseModel):
    """Profile fields synthesised by the LLM, plus the timestamp of the build.

    Empty strings / lists indicate the LLM had insufficient signal for that
    field — the UI uses that to show a "not enough chat history yet" message.
    """

    work_context: str = ""
    personal_context: str = ""
    top_of_mind: list[str] = Field(default_factory=list)
    brief_history: str = ""
    recent_months: str = ""
    last_updated: str = ""  # ISO-8601 UTC
