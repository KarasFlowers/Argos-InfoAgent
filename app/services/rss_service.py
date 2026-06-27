import asyncio
import hashlib
import logging

import feedparser
import httpx
from pydantic import ValidationError

from app.core.http_client import get_http_client
from app.core.url_safety import get_public_url
from app.models.schemas import ContentItem, RSSItem, RSSResponse
from app.services.redis_service import redis_service

logger = logging.getLogger(__name__)

MAX_RSS_FEED_BYTES = 5 * 1024 * 1024


async def fetch_and_parse_feed(url: str, client: httpx.AsyncClient) -> RSSResponse | None:
    """
    Fetches a single RSS feed, checks cache first, and parses it into our standard schema.
    """

    try:
        # Cache Key logic
        cache_key = f"rss_feed_{url}"

        # 1. Check Redis Cache
        cached_data = await redis_service.get_cache(cache_key)
        if cached_data:
            logger.info(f"Cache hit for {url}")
            return RSSResponse(**cached_data)

        # 2. Cache Miss - Fetch the RSS XML
        logger.info(f"Fetching from web: {url}")
        response = await get_public_url(client, url, timeout=10.0)
        response.raise_for_status()
        if len(response.content) > MAX_RSS_FEED_BYTES:
            raise ValueError(f"RSS feed response is too large ({len(response.content)} bytes).")

        # Log healthy fetch
        await _log_health(url, status="ok")

        # Parse the XML using feedparser
        # Pass raw bytes so feedparser can detect encoding from XML declaration
        feed = feedparser.parse(response.content)

        if not feed.entries:
            logger.warning(f"No entries found for {url}")
            return RSSResponse(source_url=url, items=[])

        source_title = feed.feed.get("title", url)

        items = []
        for entry in feed.entries[:10]:  # Limit to 10 most recent per feed
            try:
                # Extract basic fields safely with defaults
                published = entry.get("published", "") or entry.get("updated", "")
                summary = entry.get("summary", "") or entry.get("description", "")

                # Strip HTML from summary (basic cleaning)
                # In production, might want a more robust HTML parser like BeautifulSoup here

                item = RSSItem(
                    title=entry.get("title", "Unknown Title"),
                    link=entry.get("link", ""),
                    published=published,
                    summary=summary[:500],  # preview
                    source=source_title,
                )
                items.append(item)
            except ValidationError as e:
                logger.error(f"Validation error for entry in {url}: {e}")
                continue

        # 3. Cache the successful result
        response_obj = RSSResponse(source_url=url, items=items)
        try:
            # Pydantic model dump (json-compatible dict)
            # Depending on pydantic version, it could be .model_dump() or .dict()
            # We'll use model_dump() which is the v2 standard
            await redis_service.set_cache(cache_key, response_obj.model_dump(), expire_seconds=900)
            logger.info(f"Saved to cache: {url}")
        except Exception as e:
            logger.error(f"Failed to save to cache {url}: {e}")

        return response_obj

    except httpx.TimeoutException as e:
        logger.error(f"Timeout fetching feed {url}: {e}")
        await _log_health(url, status="timeout", error_message=str(e))
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching feed {url}: {e}")
        await _log_health(url, status="error", error_message=str(e))
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching feed {url}: {e}")
        await _log_health(url, status="error", error_message=str(e))
    except Exception as e:
        logger.error(f"Unexpected error parsing feed {url}: {e}")
        await _log_health(url, status="error", error_message=str(e))

    return None


async def _log_health(
    url: str,
    *,
    status: str = "ok",
    error_message: str = "",
) -> None:
    """Best-effort: update source health fields directly. Silently skip if source not in DB."""
    try:
        from datetime import UTC, datetime

        from sqlalchemy import select

        from app.core.db import AsyncSessionLocal
        from app.models.domain import Source

        async with AsyncSessionLocal() as session:
            stmt = select(Source).where(Source.url == url).limit(1)
            result = await session.execute(stmt)
            source = result.scalar_one_or_none()
            if source:
                now = datetime.now(UTC)
                if status == "ok":
                    source.last_fetched_at = now
                    source.last_error = ""
                    source.health_status = "healthy"
                else:
                    source.last_error = error_message[:500] if error_message else "unknown error"
                    # Mark degraded on first failure, unhealthy after persisted failures
                    if source.health_status == "healthy":
                        source.health_status = "degraded"
                    elif source.health_status == "degraded":
                        source.health_status = "unhealthy"
                await session.commit()
    except Exception as err:
        logger.debug("Source health logging skipped: %s", err)


async def fetch_all_feeds(urls: list[str]) -> list[RSSResponse]:
    """
    Concurrently fetches multiple RSS feeds using the shared httpx client.
    """
    client = get_http_client()

    # Create a list of async tasks
    tasks = [fetch_and_parse_feed(url, client) for url in urls]
    # Execute them concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out None values or exceptions
    valid_results = []
    for result in results:
        if isinstance(result, RSSResponse):
            valid_results.append(result)
        elif isinstance(result, Exception):
            logger.error(f"Fetch task failed with exception: {result}")

    return valid_results


def rss_responses_to_content_items(responses: list[RSSResponse]) -> list[ContentItem]:
    """Convert a list of RSSResponse objects into unified ContentItem list."""
    items: list[ContentItem] = []
    for feed in responses:
        source_url = feed.source_url
        for rss_item in feed.items:
            # MD5 used only for short deterministic ID generation, not for security
            native_id = hashlib.md5(rss_item.link.encode()).hexdigest()[:12]
            items.append(
                ContentItem(
                    id=f"rss:feed:{native_id}",
                    source_type="rss",
                    title=rss_item.title,
                    url=rss_item.link,
                    content=rss_item.summary[:300] if rss_item.summary else None,
                    author=None,
                    published_at=rss_item.published or "",
                    source_name=rss_item.source or source_url,
                    metadata={"feed_url": source_url},
                )
            )
    return items
