# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Saved chats and artifacts: ``/v1/chats`` and ``/v1/artifacts``.

The browser builds both, as it always has, and keeps them here instead of in
its own ``localStorage`` (``user_store`` explains why). Every route is scoped to
the caller: an id that belongs to someone else answers 404, the same as one
that does not exist, PUT included, so nobody overwrites another user's item by
guessing its id.

Generation is not here. ``POST /v1/artifact`` still only generates; the browser
then saves the result with ``PUT /v1/artifacts/{id}``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from ..auth.validator import TokenClaims, validate_token
from ..models.requests import Environment
from ..models.responses import ErrorResponse
from ..models.saved_items import (
    ArtifactList,
    ArtifactPut,
    ArtifactSummary,
    Chat,
    ChatList,
    ChatPut,
    ChatSummary,
    SavedArtifact,
)
from ..user_store import (
    PayloadTooLargeError,
    UserStore,
    get_artifact_store,
    get_chat_store,
    owner_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["saved-items"])

# The browser names items with crypto.randomUUID(); anything else is refused
# before it reaches OpenSearch as a document id.
ItemId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,128}$")]

_ERRORS = {500: {"model": ErrorResponse}}


def _fail(status: int, code: str, message: str) -> NoReturn:
    raise HTTPException(
        status_code=status,
        detail=ErrorResponse(error_code=code, message=message, trace_id=uuid.uuid4().hex).model_dump(),
    )


def _owner(claims: TokenClaims) -> str:
    try:
        return owner_key(claims.issuer, claims.sub)
    except ValueError:
        _fail(401, "TOKEN_WITHOUT_SUBJECT", "The token has no `sub` claim, so it cannot own saved items.")


def _get(store: UserStore, owner: str, item_id: str) -> dict:
    try:
        item = store.get(owner, item_id)
    except PermissionError:
        logger.error("%s/%s does not decrypt with the current key", store.kind.index, item_id)
        _fail(
            500,
            "SAVED_ITEM_UNREADABLE",
            "This item was encrypted with a different key and cannot be read.",
        )
    if item is None:
        _fail(404, "NOT_FOUND", "Not found.")
    return item


def _put(store: UserStore, claims: TokenClaims, item_id: str, meta: dict, data: dict) -> dict:
    try:
        entry = store.put(_owner(claims), claims.email, item_id, meta, data)
    except PayloadTooLargeError as exc:
        _fail(413, "PAYLOAD_TOO_LARGE", str(exc))
    if entry is None:
        _fail(404, "NOT_FOUND", "Not found.")
    return entry


# ── Chats ─────────────────────────────────────────────────────────────────────


@router.get("/chats", response_model=ChatList, responses=_ERRORS)
def list_chats(
    workspace_id: str | None = None,
    claims: TokenClaims = Depends(validate_token),
    store: UserStore = Depends(get_chat_store),
) -> ChatList:
    """The caller's chats, newest first, without their messages."""
    return ChatList(items=store.list(_owner(claims), {"workspace_id": workspace_id}))


@router.get("/chats/{chat_id}", response_model=Chat, responses=_ERRORS)
def get_chat(
    chat_id: ItemId,
    claims: TokenClaims = Depends(validate_token),
    store: UserStore = Depends(get_chat_store),
) -> Chat:
    return Chat(**_get(store, _owner(claims), chat_id))


@router.put("/chats/{chat_id}", response_model=ChatSummary, responses=_ERRORS)
def put_chat(
    chat_id: ItemId,
    body: ChatPut,
    claims: TokenClaims = Depends(validate_token),
    store: UserStore = Depends(get_chat_store),
) -> ChatSummary:
    """Create or replace the whole chat."""
    return ChatSummary(**_put(store, claims, chat_id, body.model_dump(exclude={"data"}), body.data))


@router.delete("/chats/{chat_id}", status_code=204, responses=_ERRORS)
def delete_chat(
    chat_id: ItemId,
    claims: TokenClaims = Depends(validate_token),
    store: UserStore = Depends(get_chat_store),
) -> Response:
    if not store.delete(_owner(claims), chat_id):
        _fail(404, "NOT_FOUND", "Not found.")
    return Response(status_code=204)


# ── Artifacts ─────────────────────────────────────────────────────────────────


@router.get("/artifacts", response_model=ArtifactList, responses=_ERRORS)
def list_artifacts(
    workspace_id: str | None = None,
    env: Environment | None = None,
    claims: TokenClaims = Depends(validate_token),
    store: UserStore = Depends(get_artifact_store),
) -> ArtifactList:
    """The caller's artifacts, newest first, without their content.

    The gallery asks for one workspace and one env, the ones the sidebar
    selects: dev and prod hold different figures, and an artifact listed
    under the wrong one is read as the other's.
    """
    return ArtifactList(
        items=store.list(_owner(claims), {"workspace_id": workspace_id, "env": env})
    )


@router.get("/artifacts/{artifact_id}", response_model=SavedArtifact, responses=_ERRORS)
def get_artifact(
    artifact_id: ItemId,
    claims: TokenClaims = Depends(validate_token),
    store: UserStore = Depends(get_artifact_store),
) -> SavedArtifact:
    return SavedArtifact(**_get(store, _owner(claims), artifact_id))


@router.put("/artifacts/{artifact_id}", response_model=ArtifactSummary, responses=_ERRORS)
def put_artifact(
    artifact_id: ItemId,
    body: ArtifactPut,
    claims: TokenClaims = Depends(validate_token),
    store: UserStore = Depends(get_artifact_store),
) -> ArtifactSummary:
    """Create or replace the whole artifact, as generated by ``POST /v1/artifact``."""
    return ArtifactSummary(
        **_put(store, claims, artifact_id, body.model_dump(exclude={"data"}), body.data)
    )
