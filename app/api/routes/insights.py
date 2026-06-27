from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.services.insights_service import (
    get_entity_timeline,
    get_topic_heatmap,
    get_topic_tree,
    get_trending_topics,
)
from app.services.research_service import research

router = APIRouter()


@router.get("/insights/heatmap")
async def get_insights_heatmap(
    session: AsyncSession = Depends(get_session),
    days: int = Query(default=7, ge=1, le=30),
):
    """
    Get a topic heatmap (category + tag counts per day) for the last N days.
    """
    return await get_topic_heatmap(session, days)


@router.get("/insights/timeline")
async def get_insights_timeline(
    session: AsyncSession = Depends(get_session),
    entity: str = Query(..., min_length=1),
    days: int = Query(default=30, ge=1, le=90),
):
    """
    Get a timeline of news items mentioning a specific entity keyword.
    """
    return await get_entity_timeline(session, entity, days)


@router.get("/insights/topic_tree")
async def get_insights_topic_tree(
    session: AsyncSession = Depends(get_session),
    days: int = Query(default=7, ge=1, le=30),
):
    """Get a hierarchical topic tree built from topic_path fields."""
    return await get_topic_tree(session, days)


@router.get("/insights/trending")
async def get_insights_trending(
    session: AsyncSession = Depends(get_session),
    days: int = Query(default=7, ge=2, le=30),
    top_n: int = Query(default=10, ge=1, le=50),
):
    """Find topics trending upward in the recent half vs prior half of the period."""
    return await get_trending_topics(session, days, top_n)


@router.post("/research")
async def deep_research(payload: dict):
    """
    Run a simplified deep research cycle on a question.

    Body: {"question": "...", "max_sub_queries": 4, "rag_top_k": 5}
    """
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="'question' is required.")

    return await research(
        question=question,
        max_sub_queries=int(payload.get("max_sub_queries", 4)),
        rag_top_k=int(payload.get("rag_top_k", 5)),
    )
