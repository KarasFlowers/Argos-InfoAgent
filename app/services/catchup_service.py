import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import SummaryItem
from app.services.db_service import db_service
from app.services.dedup_service import normalize_url

logger = logging.getLogger(__name__)


def board_catchup_days(board, default: int = 7) -> int:
    """Return the board catch-up window while preserving 0 as disabled."""
    raw_value = getattr(board, "catchup_days", None)
    if raw_value is None or raw_value == "":
        return default
    try:
        return max(0, min(int(raw_value), 30))
    except (TypeError, ValueError):
        return default


async def collect_catchup_news(
    session: AsyncSession,
    board_id: int | None,
    catchup_days: int,
    today_str: str,
    *,
    exclude_items: list | None = None,
    importance_selector: Callable[[list[dict]], Awaitable[set[int]]] | None = None,
) -> list[SummaryItem]:
    """Collect unread summary items from recent days as catchup_news."""

    def _url_key(url: str) -> str:
        return normalize_url(url).strip().lower() if url else ""

    def _headline_key(headline: str) -> str:
        return (headline or "").strip().lower()[:160]

    if catchup_days <= 0:
        return []

    unread_rows = await db_service.get_unread_summary_items(
        session,
        board_id,
        days=catchup_days,
    )
    unread_rows = [(date_value, item) for date_value, item in unread_rows if date_value != today_str]
    if not unread_rows:
        return []

    catchup_items: list[SummaryItem] = []
    seen_urls: set[str] = set()
    seen_clusters: set[int] = set()
    seen_headlines: set[str] = set()

    for item in exclude_items or []:
        url_key = _url_key(getattr(item, "original_link", ""))
        headline_key = _headline_key(getattr(item, "headline", ""))
        cluster_id = getattr(item, "cluster_id", None)
        if url_key:
            seen_urls.add(url_key)
        if cluster_id:
            seen_clusters.add(int(cluster_id))
        if headline_key:
            seen_headlines.add(headline_key)

    def _quality_score(item) -> int:
        key_points = getattr(item, "key_points", None) or []
        tags = getattr(item, "tags", None) or []
        return len(key_points) * 3 + len(tags) + len(getattr(item, "headline", "") or "")

    unread_rows.sort(key=lambda row: (row[0], _quality_score(row[1])), reverse=True)

    for date_value, item in unread_rows:
        url = getattr(item, "original_link", "") or ""
        headline = getattr(item, "headline", "") or ""
        cluster_id = getattr(item, "cluster_id", None)
        url_key = _url_key(url)
        headline_key = _headline_key(headline)
        if url_key and url_key in seen_urls:
            continue
        if cluster_id and int(cluster_id) in seen_clusters:
            continue
        if not cluster_id and headline_key and headline_key in seen_headlines:
            continue
        if url_key:
            seen_urls.add(url_key)
        if cluster_id:
            seen_clusters.add(int(cluster_id))
        if headline_key:
            seen_headlines.add(headline_key)
        catchup_items.append(
            SummaryItem(
                headline=headline,
                category=getattr(item, "category", "general") or "general",
                key_points=getattr(item, "key_points", None) or [],
                tags=getattr(item, "tags", None) or [],
                topic_path=getattr(item, "topic_path", "") or "",
                original_link=url,
                source=getattr(item, "source", "") or "",
                feedback_sentiment=getattr(item, "feedback_sentiment", None),
                persona_score=getattr(item, "persona_score", None),
                is_read=False,
                cluster_id=cluster_id,
                is_catchup=True,
                original_date=date_value,
            )
        )

    if not catchup_items:
        return []

    if importance_selector is not None:
        try:
            scored_input = [
                {"headline": item.headline, "summary": "; ".join(item.key_points)} for item in catchup_items
            ]
            keep_indices = await importance_selector(scored_input)
            catchup_items = [item for index, item in enumerate(catchup_items) if index in keep_indices]
        except Exception:
            logger.debug("Catchup importance filter skipped; keeping all items")

    return catchup_items
