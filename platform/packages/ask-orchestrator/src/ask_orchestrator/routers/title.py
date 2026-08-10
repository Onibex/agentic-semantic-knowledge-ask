"""POST /v1/title — generate a short chat session title from the opening question."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth.validator import TokenClaims, validate_token
from ..config import SettingsCache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["title"])


class TitleRequest(BaseModel):
    question: str = Field(..., min_length=1)


class TitleResponse(BaseModel):
    title: str


@router.post("/title", response_model=TitleResponse)
def generate_chat_title(
    req: TitleRequest,
    _claims: TokenClaims = Depends(validate_token),
) -> TitleResponse:
    """Return a 3-5 word title for a chat session seeded by the given question."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from ask_llm_gateway.application.factory import build_llm

    cfg = SettingsCache.get()
    llm = build_llm(cfg)

    try:
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a chat title generator. "
                        "Given a user question, respond with ONLY a concise title of 3-5 words. "
                        "No quotes, no punctuation at the end, no explanation. Use title case. "
                        "Examples: 'Top Customers By Revenue', 'Pending Purchase Orders', 'Monthly Sales Trend'"
                    )
                ),
                HumanMessage(content=req.question),
            ]
        )
        title = response.content.strip().strip('"').strip("'")
        if len(title) > 60:
            title = title[:57] + "..."
        return TitleResponse(title=title or req.question[:40])
    except Exception as exc:
        logger.warning("title generation failed: %s", exc)
        fallback = req.question[:40] + ("..." if len(req.question) > 40 else "")
        return TitleResponse(title=fallback)
