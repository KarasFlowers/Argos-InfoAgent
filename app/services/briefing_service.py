from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.domain import ContentCluster, DailySummary, NewsItem
from app.services.db_service import db_service


async def build_briefing_events(
    session: AsyncSession,
    board_id: int | None,
    root_items: list,
    as_of_date: str,
    *,
    lookback_days: int = 3,
) -> list[dict]:
    cluster_ids: list[int] = []
    for item in root_items or []:
        cluster_id = getattr(item, "cluster_id", None)
        if cluster_id and int(cluster_id) not in cluster_ids:
            cluster_ids.append(int(cluster_id))
    if not cluster_ids:
        return []

    try:
        end_date = datetime.strptime(as_of_date, "%Y-%m-%d").date()
        start_str = (end_date - timedelta(days=max(lookback_days - 1, 0))).strftime("%Y-%m-%d")
    except ValueError:
        start_str = as_of_date

    stmt = (
        select(DailySummary.date, NewsItem)
        .join(NewsItem, NewsItem.summary_id == DailySummary.id)
        .where(
            NewsItem.cluster_id.in_(cluster_ids),
            DailySummary.date >= start_str,
            DailySummary.date <= as_of_date,
        )
        .order_by(DailySummary.date.desc(), NewsItem.id.desc())
    )
    if board_id is not None:
        stmt = stmt.where(DailySummary.board_id == board_id)
    result = await session.execute(stmt)
    rows = [(date_value, item) for date_value, item in result.all()]
    if not rows:
        return []

    cluster_result = await session.execute(select(ContentCluster).where(ContentCluster.id.in_(cluster_ids)))
    clusters_by_id = {cluster.id: cluster for cluster in cluster_result.scalars().all() if cluster.id}
    read_map = await db_service.get_read_state_map(
        session,
        [item.original_link for _, item in rows if item.original_link],
        board_id,
    )

    grouped: dict[int, list[tuple[str, object]]] = {cluster_id: [] for cluster_id in cluster_ids}
    for date_value, item in rows:
        if item.cluster_id in grouped:
            grouped[int(item.cluster_id)].append((date_value, item))

    events: list[dict] = []
    for cluster_id in cluster_ids:
        items = grouped.get(cluster_id) or []
        if not items:
            continue
        cluster = clusters_by_id.get(cluster_id)
        sources: list[str] = []
        event_items: list[dict] = []
        unread_count = 0
        covered_dates: set[str] = set()
        for date_value, item in items:
            covered_dates.add(date_value)
            if item.source and item.source not in sources:
                sources.append(item.source)
            item_is_read = True if not item.original_link else read_map.get(item.original_link, False)
            if not item_is_read:
                unread_count += 1
            if len(event_items) >= 3:
                continue
            event_items.append(
                {
                    "date": date_value,
                    "headline": item.headline,
                    "category": item.category,
                    "key_points": item.key_points or [],
                    "tags": item.tags or [],
                    "topic_path": item.topic_path or "",
                    "original_link": item.original_link,
                    "source": item.source,
                    "cluster_id": cluster_id,
                    "is_read": item_is_read,
                }
            )

        latest_date = max(date_value for date_value, _ in items)
        first_date = min(date_value for date_value, _ in items)
        events.append(
            {
                "cluster_id": cluster_id,
                "title": cluster.title if cluster else items[0][1].headline,
                "summary": cluster.summary if cluster else "",
                "item_count": cluster.item_count if cluster else len(items),
                "source_count": len(sources),
                "unread_item_count": unread_count,
                "days_covered": len(covered_dates),
                "first_date": first_date,
                "latest_date": latest_date,
                "sources": sources,
                "items": event_items,
            }
        )
    return events
