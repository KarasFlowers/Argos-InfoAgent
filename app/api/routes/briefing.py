import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.core.db import get_session
from app.models.domain import DailyReportRefinementSession
from app.models.schemas import ContentItem
from app.services.briefing_service import build_briefing_events
from app.services.db_service import db_service
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

router = APIRouter()


class RefineRequest(BaseModel):
    date: str | None = None
    board: str | None = None
    instruction: str = Field(min_length=1, max_length=2000)


@router.get("/briefing")
async def get_daily_briefing(
    date: str | None = None,
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Structured daily briefing — richer than /summary.

    Returns grouped news with cluster info, source stats, and pipeline metadata.
    If no summary exists for the date, returns 404.
    """
    search_date = date or datetime.now().strftime("%Y-%m-%d")
    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None

    existing = await db_service.get_summary_by_date(session, search_date, board_id=board_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"No briefing found for {search_date}.")

    try:
        for item in existing.top_news:
            url = getattr(item, "original_link", "") or getattr(item, "url", "")
            if url:
                await db_service.mark_article_read(session, url, board_id, is_read=True, commit=False)
        await session.commit()
    except Exception:
        logger.debug("Article read tracking skipped for briefing %s", search_date)

    sections: dict[str, list] = {}
    for item in existing.top_news:
        category = item.category or "general"
        sections.setdefault(category, []).append(
            {
                "headline": item.headline,
                "key_points": item.key_points,
                "tags": item.tags,
                "topic_path": getattr(item, "topic_path", ""),
                "original_link": item.original_link,
                "source": item.source,
                "is_read": getattr(item, "is_read", False),
                "cluster_id": getattr(item, "cluster_id", None),
            }
        )

    events = []
    try:
        events = await build_briefing_events(session, board_id, existing.top_news, search_date)
    except Exception:
        logger.debug("Briefing event clustering skipped (not yet populated)")

    source_analysis = {"date": search_date, "lookback_days": 3, "items": []}
    try:
        from app.services.source_insights_service import get_source_coverage_analysis

        source_analysis = await get_source_coverage_analysis(
            session,
            board_id=board_id,
            date=search_date,
            days=3,
            limit=4,
        )
    except Exception:
        logger.debug("Source coverage analysis skipped for briefing")

    return {
        "date": existing.date,
        "board": board_obj.slug if board_obj else "default",
        "overview": existing.overview,
        "perspective": existing.perspective,
        "sections": sections,
        "events": events,
        "clusters": events,
        "source_analysis": source_analysis,
        "source_stats": existing.stats_json or {},
        "recommendation_report": {},
        "total_items": len(existing.top_news),
        "section_count": len(sections),
    }


@router.post("/briefing/refine")
async def refine_daily_briefing(
    payload: RefineRequest,
    session: AsyncSession = Depends(get_session),
):
    """Refine an existing daily briefing with a user instruction.

    Creates a DailyReportRefinementSession, re-runs LLM with the instruction
    injected into persona context, and stores the refined output.
    """
    search_date = payload.date or datetime.now().strftime("%Y-%m-%d")
    board_obj = await resolve_active_board(session, payload.board)
    board_id = board_obj.id if board_obj else None

    existing = await db_service.get_summary_by_date(session, search_date, board_id=board_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"No summary found for {search_date} to refine.")

    refinement = DailyReportRefinementSession(
        board_id=board_id,
        date=search_date,
        instruction=payload.instruction,
        original_summary_json=existing.model_dump(mode="json"),
        status="processing",
    )
    session.add(refinement)
    await session.commit()
    await session.refresh(refinement)
    session_id = refinement.id

    try:
        rebuilt_items = [
            ContentItem(
                id=f"rss:refine:{item.id}",
                source_type="rss",
                title=item.headline,
                url=item.original_link,
                source=item.source,
            )
            for item in existing.top_news
        ]

        refined, _ = await llm_service.generate_daily_summary_from_items(
            content_items=rebuilt_items,
            session=session,
            board=board_obj,
            one_time_preference=payload.instruction,
        )

        if refined:
            refinement.refined_summary_json = refined.model_dump(mode="json")
            refinement.status = "done"
        else:
            refinement.status = "failed"
            refinement.error_message = "LLM returned no output"
    except Exception as exc:
        refinement.status = "failed"
        refinement.error_message = str(exc)[:500]

    refinement.finished_at = datetime.now(UTC)
    await session.commit()

    return {
        "session_id": session_id,
        "status": refinement.status,
        "refined_summary": refinement.refined_summary_json,
        "error": refinement.error_message or None,
    }


@router.get("/briefing/refine/{session_id}")
async def get_refinement_session(
    session_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Retrieve a refinement session result."""
    stmt = select(DailyReportRefinementSession).where(DailyReportRefinementSession.id == session_id)
    result = await session.execute(stmt)
    refinement = result.scalar_one_or_none()
    if not refinement:
        raise HTTPException(status_code=404, detail="Refinement session not found.")

    return {
        "session_id": refinement.id,
        "board_id": refinement.board_id,
        "date": refinement.date,
        "instruction": refinement.instruction,
        "status": refinement.status,
        "refined_summary": refinement.refined_summary_json,
        "error": refinement.error_message or None,
        "created_at": refinement.created_at.isoformat() if refinement.created_at else None,
        "finished_at": refinement.finished_at.isoformat() if refinement.finished_at else None,
    }
