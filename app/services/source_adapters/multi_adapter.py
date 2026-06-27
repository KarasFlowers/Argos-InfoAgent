"""
Multi-source adapter.

Concurrently fetches from multiple source types (rss, hackernews, reddit,
github) configured in ``board.source_config["sources"]``, merges all
ContentItem results, and hands off to the LLM editor which runs URL dedup +
AI semantic dedup + scoring + summarisation.

Example ``board.source_config``::

    {
        "sources": {
            "rss": {"feeds": ["https://hnrss.org/frontpage"]},
            "hackernews": {"fetch_top_stories": 30, "min_score": 100},
            "reddit": {
                "subreddits": [
                    {"subreddit": "LocalLLaMA", "min_score": 50}
                ],
                "fetch_comments": 5
            },
            "github": {
                "repos": [{"owner": "openai", "repo": "whisper"}]
            }
        }
    }
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.schemas import ContentItem
from app.services.source_adapters.base import SourceAdapter

if TYPE_CHECKING:
    from app.models.domain import Board
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


class MultiSourceAdapter(SourceAdapter):
    """Fetch from multiple source types in parallel, merge, then summarise."""

    source_type = "multi"

    async def produce(
        self,
        board: "Board",
        session: AsyncSession,
        one_time_preference: str | None = None,
        since_hours: int = 24,
    ) -> "tuple[DailySummaryResponse | None, dict[str, str]]":
        config = board.source_config or {}

        sources_cfg: dict = config.get("sources", {})
        source_table_rss_feeds: list[str] = []
        try:
            from app.services.db_service import db_service

            source_table_rss_feeds = await db_service.get_board_rss_feeds(session, board)
        except Exception as exc:
            logger.debug("MultiSourceAdapter Source lookup skipped for board '%s': %s", board.slug, exc)

        if not sources_cfg and not source_table_rss_feeds:
            logger.warning(
                "MultiSourceAdapter: board '%s' has no 'sources' in source_config",
                board.slug,
            )
            return None, {}

        since = datetime.now(UTC) - timedelta(hours=since_hours)

        all_items: list[ContentItem] = []

        from app.core.http_client import get_http_client

        client = get_http_client()

        tasks: list[asyncio.Task] = []

        # RSS
        rss_cfg = sources_cfg.get("rss")
        if rss_cfg or source_table_rss_feeds:
            rss_cfg = dict(rss_cfg or {})
            if source_table_rss_feeds:
                rss_cfg["feeds"] = source_table_rss_feeds
            tasks.append(asyncio.create_task(self._fetch_rss(rss_cfg)))

        # Hacker News
        hn_cfg = sources_cfg.get("hackernews")
        if hn_cfg:
            tasks.append(asyncio.create_task(self._fetch_hn(hn_cfg, since, client)))

        # Reddit
        reddit_cfg = sources_cfg.get("reddit")
        if reddit_cfg:
            tasks.append(asyncio.create_task(self._fetch_reddit(reddit_cfg, since, client)))

        # GitHub
        github_cfg = sources_cfg.get("github")
        if github_cfg:
            tasks.append(asyncio.create_task(self._fetch_github(github_cfg, since, client)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning("MultiSourceAdapter sub-fetch error: %s", result)
            elif isinstance(result, list):
                all_items.extend(result)

        if not all_items:
            logger.info("MultiSourceAdapter: no items fetched for board '%s'", board.slug)
            return None, {}

        logger.info(
            "MultiSourceAdapter: %d items from %d sub-sources for board '%s'",
            len(all_items),
            len(tasks),
            board.slug,
        )

        from app.services.llm_service import llm_service

        return await llm_service.generate_daily_summary_from_items(
            all_items,
            session=session,
            one_time_preference=one_time_preference,
            board=board,
        )

    # ------------------------------------------------------------------
    # Per-source fetch helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _fetch_rss(cfg: dict) -> list[ContentItem]:
        from app.services.rss_service import fetch_all_feeds, rss_responses_to_content_items

        feeds = cfg.get("feeds", [])
        if not feeds:
            feeds = list(settings.RSS_FEEDS)
        responses = await fetch_all_feeds(feeds)
        return rss_responses_to_content_items(responses)

    @staticmethod
    async def _fetch_hn(cfg: dict, since: datetime, client: httpx.AsyncClient) -> list[ContentItem]:
        from app.scrapers.hackernews import HackerNewsScraper

        scraper_cfg = {
            "enabled": True,
            "fetch_top_stories": cfg.get("fetch_top_stories", settings.HN_FETCH_TOP_STORIES),
            "min_score": cfg.get("min_score", settings.HN_MIN_SCORE),
        }
        scraper = HackerNewsScraper(scraper_cfg, client)
        return await scraper.fetch(since)

    @staticmethod
    async def _fetch_reddit(cfg: dict, since: datetime, client: httpx.AsyncClient) -> list[ContentItem]:
        from app.scrapers.reddit import RedditScraper

        scraper_cfg = {
            "enabled": True,
            "subreddits": cfg.get("subreddits", []),
            "users": cfg.get("users", []),
            "fetch_comments": cfg.get("fetch_comments", settings.REDDIT_FETCH_COMMENTS),
        }
        scraper = RedditScraper(scraper_cfg, client)
        return await scraper.fetch(since)

    @staticmethod
    async def _fetch_github(cfg: dict, since: datetime, client: httpx.AsyncClient) -> list[ContentItem]:
        from app.scrapers.github import GitHubScraper

        scraper_cfg = {
            "enabled": True,
            "users": cfg.get("users", []),
            "repos": cfg.get("repos", []),
        }
        scraper = GitHubScraper(scraper_cfg, client)
        return await scraper.fetch(since)
