from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.api.url_params import normalize_article_url_or_400
from app.core.db import get_session
from app.services.db_service import db_service
from app.services.learning_service import get_inferred_interests
from app.services.llm_service import llm_service
from app.services.persona_training_service import get_persona_training_summary

router = APIRouter()


class PersonaCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="instruction", max_length=64)
    board_id: int | None = None  # null = global persona


class InterestOptionsRequest(BaseModel):
    headline: str = Field(min_length=1, max_length=500)
    key_points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class SaveInterestReasonRequest(BaseModel):
    content: str = Field(min_length=1, max_length=200)


class ArticleReadRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)
    board: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")


@router.get("/persona")
async def get_persona(
    board: str | None = None,
    include_global: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """
    Get active persona instructions. When board is provided, returns that
    board's personas (plus global ones if include_global=True).
    """
    board_id: int | None = None
    if board is not None:
        board_obj = await resolve_active_board(session, board)
        board_id = board_obj.id if board_obj else None
    return await db_service.get_active_personas(session, board_id=board_id, include_global=include_global)


@router.post("/persona")
async def add_persona(
    payload: PersonaCreateRequest,
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Add a new persona instruction.
    Priority: payload.board_id > ?board=slug > global (null).
    """
    target_board_id: int | None = payload.board_id
    if target_board_id is None and board:
        board_obj = await resolve_active_board(session, board)
        target_board_id = board_obj.id if board_obj else None
    await db_service.save_persona(session, payload.content, payload.category, board_id=target_board_id)
    return {"status": "ok"}


@router.delete("/persona/{persona_id}")
async def delete_persona(persona_id: int, session: AsyncSession = Depends(get_session)):
    """
    Delete a persona instruction.
    """
    await db_service.delete_persona(session, persona_id)
    return {"status": "ok"}


@router.post("/feedback/interest-options")
async def feedback_interest_options(payload: InterestOptionsRequest):
    """
    Given a just-liked article, return 3-4 LLM-suggested abstract interest
    descriptions (e.g. "新 AI 模型发布动态") for the user to choose from,
    so we can capture *real* intent rather than the literal article topic.
    """
    options = await llm_service.extract_interest_options(
        headline=payload.headline,
        key_points=payload.key_points,
        tags=payload.tags,
    )
    return {"options": options}


@router.post("/feedback/save-reason")
async def feedback_save_reason(
    payload: SaveInterestReasonRequest,
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Persist the user's chosen abstract interest reason as an `extracted`
    persona, scoped to the current board when provided.
    """
    board_id: int | None = None
    if board:
        board_obj = await resolve_active_board(session, board)
        board_id = board_obj.id if board_obj else None
    await db_service.save_persona(session, content=payload.content, category="extracted", board_id=board_id)
    return {"status": "ok"}


@router.post("/articles/read")
async def mark_article_read_endpoint(
    payload: ArticleReadRequest,
    session: AsyncSession = Depends(get_session),
):
    board_obj = await resolve_active_board(session, payload.board)
    url = normalize_article_url_or_400(payload.url)
    await db_service.mark_article_read(
        session,
        url,
        board_obj.id if board_obj else None,
        is_read=True,
    )
    return {"status": "ok", "is_read": True}


@router.delete("/articles/read")
async def mark_article_unread_endpoint(
    payload: ArticleReadRequest,
    session: AsyncSession = Depends(get_session),
):
    board_obj = await resolve_active_board(session, payload.board)
    url = normalize_article_url_or_400(payload.url)
    await db_service.mark_article_read(
        session,
        url,
        board_obj.id if board_obj else None,
        is_read=False,
    )
    return {"status": "ok", "is_read": False}


@router.get("/persona/inferred")
async def get_inferred_persona(session: AsyncSession = Depends(get_session)):
    """
    Analyze feedback history to infer user interests.
    """
    return await get_inferred_interests(session)


@router.get("/persona/training")
async def get_persona_training(
    board: str | None = None,
    limit: int = Query(default=5, ge=1, le=10),
    session: AsyncSession = Depends(get_session),
):
    """Compact training dashboard for the current board's personalization state."""
    board_obj = await resolve_active_board(session, board) if board is not None else None
    board_id = board_obj.id if board_obj else None
    board_slug = board_obj.slug if board_obj else (board or "default")
    return await get_persona_training_summary(
        session,
        board_id=board_id,
        board_slug=board_slug,
        limit=limit,
    )


@router.get("/preferences")
async def get_explicit_preferences(
    board: str | None = None,
    include_global: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """
    Get all explicit preference tags grouped by category, optionally scoped to a board.
    """
    board_id: int | None = None
    if board is not None:
        board_obj = await resolve_active_board(session, board)
        board_id = board_obj.id if board_obj else None

    return await db_service.get_explicit_preferences_detailed(session, board_id=board_id, include_global=include_global)
