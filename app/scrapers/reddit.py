"""Reddit scraper — ported from Horizon."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.models.schemas import ContentItem
from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

REDDIT_BASE = "https://www.reddit.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
REDDIT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{REDDIT_BASE}/",
}
MAX_COMMENT_CONCURRENCY = 2


class RedditScraper(BaseScraper):
    """Scraper for Reddit posts and comments.

    Expected config shape::

        {
            "enabled": true,
            "subreddits": [
                {"subreddit": "LocalLLaMA", "sort": "hot", "time_filter": "day",
                 "fetch_limit": 25, "min_score": 10}
            ],
            "users": [
                {"username": "spez", "sort": "new", "fetch_limit": 10}
            ],
            "fetch_comments": 5
        }
    """

    def __init__(self, config: dict, http_client: httpx.AsyncClient):
        super().__init__(config, http_client)
        self._comment_semaphore = asyncio.Semaphore(MAX_COMMENT_CONCURRENCY)

    async def fetch(self, since: datetime) -> list[ContentItem]:
        if not self.config.get("enabled", True):
            return []

        tasks: list = []
        for sub in self.config.get("subreddits", []):
            if sub.get("enabled", True):
                tasks.append(self._fetch_subreddit(sub, since))
        for user in self.config.get("users", []):
            if user.get("enabled", True):
                tasks.append(self._fetch_user(user, since))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        items: list[ContentItem] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Error fetching Reddit source: %s", result)
            elif isinstance(result, list):
                items.extend(result)
        return items

    # ------------------------------------------------------------------
    # Subreddit / user fetchers
    # ------------------------------------------------------------------

    async def _fetch_subreddit(self, cfg: dict, since: datetime) -> list[ContentItem]:
        sort = cfg.get("sort", "hot")
        params: dict[str, Any] = {"limit": min(cfg.get("fetch_limit", 25), 100), "raw_json": 1}
        if sort in ("top", "controversial"):
            params["t"] = cfg.get("time_filter", "day")

        url = f"{REDDIT_BASE}/r/{cfg['subreddit']}/{sort}.json"
        data = await self._reddit_get(url, params)
        if not data:
            return []

        posts = [child["data"] for child in data.get("data", {}).get("children", []) if child.get("kind") == "t3"]
        return await self._process_posts(posts, since, "subreddit", cfg["subreddit"], cfg.get("min_score", 10))

    async def _fetch_user(self, cfg: dict, since: datetime) -> list[ContentItem]:
        params: dict[str, Any] = {
            "limit": min(cfg.get("fetch_limit", 10), 100),
            "sort": cfg.get("sort", "new"),
            "raw_json": 1,
        }
        url = f"{REDDIT_BASE}/user/{cfg['username']}/submitted.json"
        data = await self._reddit_get(url, params)
        if not data:
            return []

        posts = [child["data"] for child in data.get("data", {}).get("children", []) if child.get("kind") == "t3"]
        return await self._process_posts(posts, since, "user", cfg["username"], min_score=0)

    # ------------------------------------------------------------------
    # Post processing helpers
    # ------------------------------------------------------------------

    async def _process_posts(
        self,
        posts: list[dict],
        since: datetime,
        subtype: str,
        source_name: str,
        min_score: int,
    ) -> list[ContentItem]:
        fetch_comments = self.config.get("fetch_comments", 5)
        valid_posts: list[dict] = []
        comment_tasks: list = []

        for post in posts:
            created = datetime.fromtimestamp(post.get("created_utc", 0), tz=UTC)
            if created < since:
                continue
            if post.get("score", 0) < min_score:
                continue
            valid_posts.append(post)
            if fetch_comments > 0:
                comment_tasks.append(self._fetch_comments(post.get("subreddit", ""), post["id"]))
            else:
                comment_tasks.append(self._empty_comments())

        if not valid_posts:
            return []

        all_comments = await asyncio.gather(*comment_tasks, return_exceptions=True)
        items: list[ContentItem] = []
        for post, comments in zip(valid_posts, all_comments, strict=False):
            if isinstance(comments, Exception):
                comments = []
            item = self._parse_post(post, comments, subtype)
            if item:
                items.append(item)
        return items

    @staticmethod
    async def _empty_comments() -> list[dict]:
        return []

    async def _fetch_comments(self, subreddit: str, post_id: str) -> list[dict]:
        fetch_limit = self.config.get("fetch_comments", 5)
        url = f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json"
        params = {"limit": fetch_limit, "depth": 1, "sort": "top", "raw_json": 1}

        async with self._comment_semaphore:
            data = await self._reddit_get(url, params)
        if not data or not isinstance(data, list) or len(data) < 2:
            return []

        comments: list[dict] = []
        for child in data[1].get("data", {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            c = child["data"]
            if c.get("body") and c.get("distinguished") != "moderator":
                comments.append(c)

        comments.sort(key=lambda c: c.get("score", 0), reverse=True)
        return comments[:fetch_limit]

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_post(self, post: dict, comments: list[dict], subtype: str) -> ContentItem | None:
        post_id = post["id"]
        title = post.get("title", "")
        is_self = post.get("is_self", False)
        subreddit = post.get("subreddit", "")
        discussion_url = f"https://www.reddit.com{post.get('permalink', '')}"
        url = discussion_url if is_self else post.get("url", discussion_url)
        author = post.get("author", "unknown")
        created = datetime.fromtimestamp(post.get("created_utc", 0), tz=UTC)

        parts: list[str] = []
        if post.get("selftext"):
            text = post["selftext"]
            if len(text) > 1500:
                text = text[:1497] + "..."
            parts.append(text)

        if comments:
            parts.append("\n--- Top Comments ---")
            for c in comments:
                commenter = c.get("author", "anon")
                body = c.get("body", "").strip()
                if len(body) > 500:
                    body = body[:497] + "..."
                score = c.get("score", 0)
                parts.append(f"[{commenter} ({score} pts)]: {body}")

        content = "\n\n".join(parts)

        return ContentItem(
            id=self._generate_id("reddit", subtype, post_id),
            source_type="reddit",
            title=title,
            url=url,
            content=content,
            author=author,
            published_at=created.isoformat(),
            source_name=f"r/{subreddit}" if subreddit else "Reddit",
            metadata={
                "score": post.get("score", 0),
                "upvote_ratio": post.get("upvote_ratio"),
                "num_comments": post.get("num_comments", 0),
                "subreddit": subreddit,
                "is_self": is_self,
                "flair": post.get("link_flair_text"),
                "discussion_url": discussion_url,
            },
        )

    # ------------------------------------------------------------------
    # HTTP helper with rate-limit retry
    # ------------------------------------------------------------------

    async def _reddit_get(self, url: str, params: dict, *, _max_retries: int = 3) -> Any | None:
        backoff = 1.0
        last_exc: Exception | None = None
        for attempt in range(_max_retries + 1):
            try:
                response = await self.client.get(url, params=params, headers=REDDIT_HEADERS, follow_redirects=True)
                if response.status_code in (429, 503):
                    retry_after = float(response.headers.get("Retry-After", backoff))
                    if attempt < _max_retries:
                        logger.warning(
                            "Reddit %d for %s, retrying in %.1fs (attempt %d/%d)",
                            response.status_code,
                            url,
                            retry_after,
                            attempt + 1,
                            _max_retries,
                        )
                        await asyncio.sleep(retry_after)
                        backoff = min(backoff * 2, 30)
                        continue
                    response.raise_for_status()
                if response.status_code == 403 and "/comments/" in url:
                    logger.info("Reddit blocked comments for %s; continuing without", url)
                    return None
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                last_exc = e
                if attempt < _max_retries:
                    logger.warning(
                        "Reddit request error for %s: %s, retrying in %.1fs",
                        url,
                        e,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                break
        logger.warning("Reddit request failed for %s after %d retries: %s", url, _max_retries, last_exc)
        return None
