# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Request / response models for the saved chats and artifacts endpoints.

The browser builds a chat or an artifact and owns its shape; the server keeps
it. So each body has the fields a list needs, typed, and the rest under
``data``, which the server stores encrypted and hands back untouched.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .requests import Environment


class ChatPut(BaseModel):
    workspace_id: str = Field(..., min_length=1)
    title: str
    data: dict[str, Any] = Field(
        ..., description="The chat as the browser holds it: session id and messages."
    )


class ChatSummary(BaseModel):
    id: str
    workspace_id: str
    title: str
    created_at: str
    updated_at: str


class Chat(ChatSummary):
    data: dict[str, Any]


class ChatList(BaseModel):
    items: list[ChatSummary]


class ArtifactPut(BaseModel):
    workspace_id: str = Field(..., min_length=1)
    env: Environment
    name: str
    artifact_type: str
    format: str
    data: dict[str, Any] = Field(
        ..., description="The artifact as the browser holds it: document, datasets, request."
    )


class ArtifactSummary(BaseModel):
    id: str
    workspace_id: str
    env: Environment
    name: str
    artifact_type: str
    format: str
    created_at: str
    updated_at: str


class SavedArtifact(ArtifactSummary):
    data: dict[str, Any]


class ArtifactList(BaseModel):
    items: list[ArtifactSummary]
