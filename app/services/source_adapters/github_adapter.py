"""
GitHub source adapter.

Reads ``board.source_config`` for GitHub-specific settings (users, repos),
fetches via the GitHub scraper, and hands off to the LLM editor.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.source_adapters.base import SourceAdapter

if TYPE_CHECKING:
    from app.models.domain import Board
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


class GitHubAdapter(SourceAdapter):
    """Fetch GitHub user events & repo releases, then generate a curated summary."""

    source_type = "github"

    async def produce(
        self,
        board: "Board",
        session: AsyncSession,
        one_time_preference: str | None = None,
        since_hours: int = 24,
    ) -> "tuple[DailySummaryResponse | None, dict[str, str]]":
        from app.core.http_client import get_http_client
        from app.scrapers.github import GitHubScraper

        config = board.source_config or {}

        scraper_config = {
            "enabled": True,
            "users": config.get("users", []),
            "repos": config.get("repos", []),
        }

        since = datetime.now(UTC) - timedelta(hours=since_hours)

        client = get_http_client()
        scraper = GitHubScraper(scraper_config, client)
        items = await scraper.fetch(since)

        if not items:
            logger.info("GitHub adapter: no items fetched for board '%s'", board.slug)
            return None, {}

        from app.services.llm_service import llm_service

        return await llm_service.generate_daily_summary_from_items(
            items,
            session=session,
            one_time_preference=one_time_preference,
            board=board,
        )
