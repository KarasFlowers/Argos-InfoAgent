"""
Insights Service — 历史 / 跨天洞察最小切片

Provides aggregations across the last N days of summaries:
- ``topic_heatmap``: tag/category → list of (date, count) over N days.
- ``entity_timeline``: for a given entity keyword, list of
  (date, headline, category, link) where it was mentioned.

We rely on the existing structured fields (``category``, ``tags``)
plus a cheap substring search in ``headline``+``key_points`` for entities.
No new tables, no new LLM calls, no extra infra cost.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import DailySummary, NewsItem

logger = logging.getLogger(__name__)


def _last_n_dates(days: int) -> list[str]:
    """Return ISO date strings for the last *days* days, oldest first."""
    today = datetime.now()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]


async def _load_items_within(session: AsyncSession, days: int) -> list[tuple[str, NewsItem]]:
    """Return [(date, NewsItem)] for summaries within the last *days* days."""
    min_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    stmt = select(DailySummary).where(DailySummary.date >= min_date).order_by(desc(DailySummary.date))
    result = await session.execute(stmt)
    summaries = result.scalars().all()

    rows: list[tuple[str, NewsItem]] = []
    if not summaries:
        return rows

    summary_ids = [s.id for s in summaries]
    id_to_date = {s.id: s.date for s in summaries}

    news_stmt = select(NewsItem).where(NewsItem.summary_id.in_(summary_ids))
    news_result = await session.execute(news_stmt)
    for item in news_result.scalars().all():
        rows.append((id_to_date[item.summary_id], item))
    return rows


# -----------------------------------------------------------------
# Public API
# -----------------------------------------------------------------


async def get_topic_heatmap(session: AsyncSession, days: int = 7) -> dict:
    """
    Return topic heatmap for the last *days* days.

    Output shape::

        {
          "dates": ["2026-04-15", ..., "2026-04-21"],
          "topics": [
            {"name": "AI",       "counts": [3, 4, 2, 5, 1, 2, 3], "total": 20},
            {"name": "Hardware", "counts": [0, 1, 0, 2, 1, 0, 0], "total": 4},
            ...
          ]
        }
    """
    dates = _last_n_dates(days)
    date_index = {d: i for i, d in enumerate(dates)}

    # topic -> counts[days]
    buckets: dict[str, list[int]] = defaultdict(lambda: [0] * days)

    rows = await _load_items_within(session, days)
    for date, item in rows:
        idx = date_index.get(date)
        if idx is None:
            continue

        # Count the category...
        if item.category:
            buckets[item.category][idx] += 1

        # tags is a native JSON column → already a Python list
        raw_tags = item.tags if isinstance(item.tags, list) else []
        for tag in raw_tags:
            if not isinstance(tag, str):
                continue
            clean = tag.lstrip("#").strip()
            if clean:
                buckets[clean][idx] += 1

    # Sort topics by total occurrences, cap to top-15 to keep UI tidy
    topics_sorted = sorted(
        ({"name": name, "counts": counts, "total": sum(counts)} for name, counts in buckets.items()),
        key=lambda x: x["total"],
        reverse=True,
    )[:15]

    return {"dates": dates, "topics": topics_sorted}


async def get_entity_timeline(
    session: AsyncSession,
    entity: str,
    days: int = 30,
) -> dict:
    """
    For a given entity keyword, return every news item in the last *days*
    whose headline or key_points contain it (case-insensitive).

    Output::

        {
          "entity": "OpenAI",
          "days": 30,
          "total": 12,
          "items": [
            {"date": "2026-04-21",
             "headline": "...",
             "category": "AI",
             "link": "...",
             "source": "..."},
            ...
          ]
        }
    """
    query = entity.strip()
    if not query:
        return {"entity": entity, "days": days, "total": 0, "items": []}

    needle = query.lower()
    rows = await _load_items_within(session, days)
    items: list[dict] = []

    for date, item in rows:
        haystack = (item.headline or "").lower()
        if needle not in haystack:
            # key_points is a native JSON column → already a list
            raw_kp = item.key_points if isinstance(item.key_points, list) else []
            joined = " ".join(raw_kp).lower()
            if needle not in joined:
                continue

        items.append(
            {
                "date": date,
                "headline": item.headline,
                "category": item.category or "Uncategorized",
                "link": item.original_link,
                "source": item.source,
            }
        )

    # Ensure the list is sorted newest-first (same order our loader returned).
    items.sort(key=lambda x: x["date"], reverse=True)
    return {"entity": query, "days": days, "total": len(items), "items": items}


async def get_topic_tree(session: AsyncSession, days: int = 7) -> dict:
    """
    Build a hierarchical topic tree from ``topic_path`` fields.

    Each ``topic_path`` is a slash-separated string like ``"AI/LLM/微调"``.
    The tree is aggregated over the last *days* days.

    Output::

        {
          "tree": {
            "AI": {"count": 15, "children": {"LLM": {"count": 8, "children": {...}}}},
            "Hardware": {"count": 3, "children": {}}
          }
        }
    """
    rows = await _load_items_within(session, days)

    root: dict[str, dict] = {}

    for _date, item in rows:
        path = (item.topic_path or "").strip()
        if not path:
            # Fallback: use category as a single-level path
            path = item.category or "Uncategorized"

        parts = [p.strip() for p in path.split("/") if p.strip()]
        if not parts:
            continue

        node = root
        for part in parts:
            if part not in node:
                node[part] = {"count": 0, "children": {}}
            node[part]["count"] += 1
            node = node[part]["children"]

    return {"tree": root}


async def get_trending_topics(session: AsyncSession, days: int = 7, top_n: int = 10) -> dict:
    """
    Find topics whose frequency has increased the most in recent days
    compared to the prior period. Uses ``topic_path`` and ``category``.

    Output::

        {
          "trending": [
            {"topic": "AI/LLM", "recent_count": 8, "prior_count": 3, "delta": 5},
            ...
          ]
        }
    """

    half = days // 2
    if half < 1:
        half = 1

    rows = await _load_items_within(session, days)

    # Split into recent half and prior half
    today = datetime.now()
    recent_cutoff = (today - timedelta(days=half)).strftime("%Y-%m-%d")

    recent: dict[str, int] = defaultdict(int)
    prior: dict[str, int] = defaultdict(int)

    for date, item in rows:
        path = (item.topic_path or "").strip()
        if not path:
            path = item.category or "Uncategorized"

        # Use first 2 levels of the path for trending
        parts = [p.strip() for p in path.split("/") if p.strip()]
        topic_key = "/".join(parts[:2]) if len(parts) >= 2 else parts[0] if parts else path

        if date >= recent_cutoff:
            recent[topic_key] += 1
        else:
            prior[topic_key] += 1

    # Compute deltas
    all_topics = set(recent.keys()) | set(prior.keys())
    trending = []
    for topic in all_topics:
        rc = recent.get(topic, 0)
        pc = prior.get(topic, 0)
        delta = rc - pc
        if delta > 0:
            trending.append({"topic": topic, "recent_count": rc, "prior_count": pc, "delta": delta})

    trending.sort(key=lambda x: x["delta"], reverse=True)
    return {"trending": trending[:top_n]}
