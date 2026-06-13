"""Helpers for the personalization training panel."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import DailySummary, NewsItem, UserFeedback
from app.services.learning_service import get_inferred_interests
from app.services.repositories import db_service


async def get_persona_training_summary(
    session: AsyncSession,
    *,
    board_id: int | None = None,
    board_slug: str | None = None,
    limit: int = 5,
) -> dict:
    """Build a lightweight training dashboard for the persona panel."""
    pref_groups = await db_service.get_explicit_preferences_detailed(
        session,
        board_id=board_id,
        include_global=True,
    )
    pref_counts = {key: len(value or []) for key, value in pref_groups.items()}

    feedback_rows = list(
        (
            await session.execute(
                select(UserFeedback).order_by(desc(UserFeedback.created_at), desc(UserFeedback.id))
            )
        ).scalars().all()
    )

    article_info: dict[str, dict] = {}
    if feedback_rows:
        feedback_urls = [row.article_url for row in feedback_rows if row.article_url]
        stmt = (
            select(
                DailySummary.date,
                NewsItem.original_link,
                NewsItem.headline,
                NewsItem.source,
                NewsItem.category,
            )
            .join(NewsItem, NewsItem.summary_id == DailySummary.id)
            .where(NewsItem.original_link.in_(feedback_urls))
            .order_by(DailySummary.date.desc(), NewsItem.id.desc())
        )
        if board_id is not None:
            stmt = stmt.where(DailySummary.board_id == board_id)
        result = await session.execute(stmt)
        for date_value, url, headline, source, category in result.all():
            if not url or url in article_info:
                continue
            article_info[url] = {
                "date": date_value,
                "headline": headline,
                "source": source,
                "category": category,
            }

    feedback_items: list[dict] = []
    seen_urls: set[str] = set()
    for row in feedback_rows:
        url = row.article_url or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        info = article_info.get(url)
        if board_id is not None and info is None:
            continue

        feedback_items.append(
            {
                "url": url,
                "headline": (info or {}).get("headline") or url,
                "source": (info or {}).get("source") or "",
                "category": (info or {}).get("category") or "",
                "date": (info or {}).get("date"),
                "sentiment": row.sentiment,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    liked_items = [item for item in feedback_items if item["sentiment"] == 1]
    disliked_items = [item for item in feedback_items if item["sentiment"] == -1]

    top_categories = Counter(
        item["category"] for item in liked_items if item.get("category")
    ).most_common(limit)
    top_sources = Counter(
        item["source"] for item in liked_items if item.get("source")
    ).most_common(limit)

    return {
        "board": board_slug or "default",
        "feedback_summary": {
            "liked_count": len(liked_items),
            "disliked_count": len(disliked_items),
            "focus_topic_count": pref_counts.get("focus_topic", 0),
            "block_topic_count": pref_counts.get("block_topic", 0),
            "prefer_source_count": pref_counts.get("prefer_source", 0),
            "avoid_source_count": pref_counts.get("avoid_source", 0),
        },
        "inferred_interests": await get_inferred_interests(session, limit=limit, board_id=board_id),
        "top_categories": [{"name": name, "count": count} for name, count in top_categories],
        "top_sources": [{"name": name, "count": count} for name, count in top_sources],
        "recent_feedback": feedback_items[:limit],
    }
