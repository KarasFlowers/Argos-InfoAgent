"""Hacker News scraper — ported from Horizon."""

import asyncio
import logging
import re
from datetime import UTC, datetime

import httpx

from app.models.schemas import ContentItem
from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

TOP_COMMENTS_LIMIT = 5


class HackerNewsScraper(BaseScraper):
    """Scraper for Hacker News stories with top comments."""

    def __init__(self, config: dict, http_client: httpx.AsyncClient):
        super().__init__(config, http_client)
        self.base_url = "https://hacker-news.firebaseio.com/v0"

    async def fetch(self, since: datetime) -> list[ContentItem]:
        if not self.config.get("enabled", True):
            return []

        try:
            response = await self.client.get(f"{self.base_url}/topstories.json")
            response.raise_for_status()
            story_ids = response.json()

            fetch_count = self.config.get("fetch_top_stories", 30)
            story_ids = story_ids[:fetch_count]

            tasks = [self._fetch_item(sid) for sid in story_ids]
            stories = await asyncio.gather(*tasks, return_exceptions=True)

            min_score = self.config.get("min_score", 100)
            valid_stories: list[dict] = []
            comment_tasks: list = []

            for story in stories:
                if isinstance(story, Exception) or story is None:
                    continue
                if story.get("score", 0) < min_score:
                    continue
                published_at = datetime.fromtimestamp(story["time"], tz=UTC)
                if published_at < since:
                    continue
                valid_stories.append(story)
                comment_ids = story.get("kids", [])[:TOP_COMMENTS_LIMIT]
                comment_tasks.append(self._fetch_comments(comment_ids))

            all_comments = await asyncio.gather(*comment_tasks, return_exceptions=True)

            items: list[ContentItem] = []
            for story, comments in zip(valid_stories, all_comments, strict=False):
                if isinstance(comments, Exception):
                    comments = []
                item = self._parse_story(story, comments)
                if item:
                    items.append(item)
            return items

        except httpx.HTTPError as e:
            logger.warning("Error fetching Hacker News stories: %s", e)
            return []

    async def _fetch_item(self, item_id: int) -> dict | None:
        try:
            resp = await self.client.get(f"{self.base_url}/item/{item_id}.json")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            return None

    async def _fetch_comments(self, comment_ids: list[int]) -> list[dict]:
        if not comment_ids:
            return []
        tasks = [self._fetch_item(cid) for cid in comment_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        comments = []
        for r in results:
            if isinstance(r, dict) and r.get("text") and not r.get("deleted") and not r.get("dead"):
                comments.append(r)
        return comments

    def _parse_story(self, story: dict, comments: list[dict]) -> ContentItem | None:
        story_id = story["id"]
        title = story.get("title", "")
        url = story.get("url", f"https://news.ycombinator.com/item?id={story_id}")
        author = story.get("by", "unknown")
        published_at = datetime.fromtimestamp(story["time"], tz=UTC)

        parts: list[str] = []
        if story.get("text"):
            parts.append(story["text"])

        if comments:
            parts.append("\n--- Top Comments ---")
            for c in comments:
                commenter = c.get("by", "anon")
                text = c.get("text", "")
                text = re.sub(r"<[^>]+>", " ", text).strip()
                if len(text) > 500:
                    text = text[:497] + "..."
                parts.append(f"[{commenter}]: {text}")

        content = "\n\n".join(parts)
        hn_discussion = f"https://news.ycombinator.com/item?id={story_id}"

        return ContentItem(
            id=self._generate_id("hackernews", "story", str(story_id)),
            source_type="hackernews",
            title=title,
            url=url,
            content=content,
            author=author,
            published_at=published_at.isoformat(),
            source_name="Hacker News",
            metadata={
                "score": story.get("score", 0),
                "descendants": story.get("descendants", 0),
                "discussion_url": hn_discussion,
                "comment_count": len(comments),
            },
        )
