from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.core.db import get_session
from app.models.schemas import SummaryHistoryResponse
from app.services.db_service import db_service
from app.services.llm_service import llm_service

router = APIRouter()


@router.get("/history", response_model=SummaryHistoryResponse)
async def get_summary_history(
    limit: int = 7,
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Retrieve lightweight archive cards and weekly recap for recent summaries.
    """
    safe_limit = max(1, min(limit, 30))
    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None
    return await db_service.get_summary_history(session, limit=safe_limit, board_id=board_id)


@router.get("/history/weekly_insight")
async def get_weekly_insight(
    limit: int = 7,
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Generate a deep, structured weekly consolidation from recent summaries.
    """
    safe_limit = max(1, min(limit, 10))
    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None

    history = await db_service.get_summary_history(session, limit=safe_limit, board_id=board_id)
    if not history.archive_items:
        raise HTTPException(status_code=404, detail="No history found to summarize.")

    summaries_data = []
    for item in history.archive_items:
        full = await db_service.get_summary_by_date(session, item.date, board_id=board_id)
        if full:
            summaries_data.append(full.model_dump())

    if not summaries_data:
        raise HTTPException(status_code=404, detail="Failed to retrieve history content.")

    insight = await llm_service.generate_weekly_consolidation(
        summaries_data, output_language=getattr(board_obj, "output_language", None)
    )
    if not insight:
        raise HTTPException(status_code=500, detail="Failed to generate weekly insight.")

    return {"weekly_insight": insight}


@router.get("/history/weekly_report")
async def get_weekly_report(
    limit: int = 7,
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Generate a structured weekly report with themes, stats, and editorial.
    Multi-stage LLM pipeline (fast -> fast -> smart).
    """
    safe_limit = max(1, min(limit, 10))
    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None

    history = await db_service.get_summary_history(session, limit=safe_limit, board_id=board_id)
    if not history.archive_items:
        raise HTTPException(status_code=404, detail="No history found to summarize.")

    summaries_data = []
    for item in history.archive_items:
        full = await db_service.get_summary_by_date(session, item.date, board_id=board_id)
        if full:
            summaries_data.append(full.model_dump())

    if not summaries_data:
        raise HTTPException(status_code=404, detail="Failed to retrieve history content.")

    report = await llm_service.generate_structured_weekly_report(
        summaries_data, output_language=getattr(board_obj, "output_language", None)
    )
    if not report:
        raise HTTPException(status_code=500, detail="Failed to generate weekly report.")

    return report


@router.get("/cache")
async def get_cache_overview(
    limit: int = 14,
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """All stored summaries with viewed status for cache viewer."""
    safe_limit = max(1, min(limit, 30))
    board_obj = await resolve_active_board(session, board) if board else None
    board_id = board_obj.id if board_obj else None
    return await db_service.get_cache_overview(session, limit=safe_limit, board_id=board_id)
