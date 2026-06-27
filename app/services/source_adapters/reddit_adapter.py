"""
Reddit source adapter.

Reads ``board.source_config`` for Reddit-specific settings (subreddits, users,
fetch_comments), fetches via the Reddit scraper, and hands off to the LLM editor.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.source_adapters.base import SourceAdapter

if TYPE_CHECKING:
    from app.models.domain import Board
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


class RedditAdapter(SourceAdapter):
    """Fetch Reddit posts + comments, then generate a curated summary."""

    source_type = "reddit"

    async def produce(
        self,
        board: "Board",
        session: AsyncSession,
        one_time_preference: str | None = None,
        since_hours: int = 24,
    ) -> "tuple[DailySummaryResponse | None, dict[str, str]]":
        from app.core.http_client import get_http_client
        from app.scrapers.reddit import RedditScraper

        config = board.source_config or {}

        scraper_config = {
            "enabled": True,
            "subreddits": config.get("subreddits", []),
            "users": config.get("users", []),
            "fetch_comments": config.get("fetch_comments", settings.REDDIT_FETCH_COMMENTS),
        }

        since = datetime.now(UTC) - timedelta(hours=since_hours)

        client = get_http_client()
        scraper = RedditScraper(scraper_config, client)
        items = await scraper.fetch(since)

        if not items:
            logger.info("Reddit adapter: no items fetched for board '%s'", board.slug)
            return None, {}

        from app.services.llm_service import llm_service

        return await llm_service.generate_daily_summary_from_items(
            items,
            session=session,
            one_time_preference=one_time_preference,
            board=board,
        )
