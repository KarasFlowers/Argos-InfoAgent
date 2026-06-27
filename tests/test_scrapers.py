"""
test_scrapers.py - Unit tests for HN, Reddit, GitHub scrapers.

Uses mocked HTTP responses so no real network calls are made.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.models.schemas import ContentItem

# ---------------------------------------------------------------------------
# Hacker News
# ---------------------------------------------------------------------------


@pytest.fixture
def hn_config():
    return {"enabled": True, "fetch_top_stories": 5, "min_score": 0}


@pytest.mark.anyio
async def test_hn_scraper_returns_content_items(hn_config):
    """HN scraper should produce ContentItem objects from mocked API data."""
    from app.scrapers.hackernews import HackerNewsScraper

    top_ids = [1, 2, 3]
    story = {
        "id": 1,
        "type": "story",
        "title": "Test Story",
        "url": "https://example.com/test",
        "by": "author",
        "time": int(datetime.now(UTC).timestamp()),
        "score": 200,
        "descendants": 5,
        "kids": [10],
    }
    comment = {
        "id": 10,
        "type": "comment",
        "by": "commenter",
        "text": "Great article!",
        "time": int(datetime.now(UTC).timestamp()),
    }

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        if "topstories" in url:
            resp.json = MagicMock(return_value=top_ids)
        elif "/1.json" in url:
            resp.json = MagicMock(return_value=story)
        elif "/10.json" in url:
            resp.json = MagicMock(return_value=comment)
        else:
            resp.json = MagicMock(return_value=None)
        return resp

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = mock_get

    scraper = HackerNewsScraper(hn_config, client)
    since = datetime.now(UTC) - timedelta(hours=24)
    items = await scraper.fetch(since)

    assert len(items) >= 1
    assert all(isinstance(i, ContentItem) for i in items)
    assert items[0].source_type == "hackernews"
    assert items[0].title == "Test Story"


@pytest.mark.anyio
async def test_hn_scraper_empty_when_no_stories(hn_config):
    """HN scraper should return empty list when API returns no story IDs."""
    from app.scrapers.hackernews import HackerNewsScraper

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=[])
        return resp

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = mock_get

    scraper = HackerNewsScraper(hn_config, client)
    since = datetime.now(UTC) - timedelta(hours=24)
    items = await scraper.fetch(since)
    assert items == []


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------


@pytest.fixture
def reddit_config():
    return {
        "enabled": True,
        "subreddits": [{"subreddit": "python", "min_score": 0}],
        "users": [],
        "fetch_comments": 2,
    }


@pytest.mark.anyio
async def test_reddit_scraper_returns_content_items(reddit_config):
    """Reddit scraper should produce ContentItem objects from mocked data."""
    from app.scrapers.reddit import RedditScraper

    post_data = {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "abc123",
                        "title": "Python 4.0 released",
                        "url": "https://python.org/4",
                        "selftext": "Big update!",
                        "author": "guido",
                        "created_utc": datetime.now(UTC).timestamp(),
                        "score": 999,
                        "upvote_ratio": 0.98,
                        "num_comments": 50,
                        "subreddit": "python",
                        "is_self": True,
                        "link_flair_text": "News",
                        "permalink": "/r/python/comments/abc123/python40/",
                    },
                }
            ]
        },
    }
    comments_data = {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {
                        "body": "Amazing news!",
                        "author": "fan",
                        "score": 10,
                    },
                }
            ]
        },
    }

    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        if ".json" in url and "comments" not in url:
            resp.json = MagicMock(return_value=post_data)
        else:
            resp.json = MagicMock(return_value=[{}, comments_data])
        call_count += 1
        return resp

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = mock_get

    scraper = RedditScraper(reddit_config, client)
    since = datetime.now(UTC) - timedelta(hours=24)
    items = await scraper.fetch(since)

    assert len(items) >= 1
    assert all(isinstance(i, ContentItem) for i in items)
    assert items[0].source_type == "reddit"


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


@pytest.fixture
def github_config():
    return {
        "enabled": True,
        "users": [{"username": "octocat"}],
        "repos": [],
    }


@pytest.mark.anyio
async def test_github_scraper_returns_content_items(github_config):
    """GitHub scraper should produce ContentItem objects from mocked events."""
    from app.scrapers.github import GitHubScraper

    events = [
        {
            "id": "evt1",
            "type": "PushEvent",
            "repo": {"name": "octocat/hello-world"},
            "created_at": datetime.now(UTC).isoformat(),
            "payload": {"commits": [{"message": "Initial commit", "sha": "abc123"}]},
        }
    ]

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=events)
        return resp

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = mock_get

    scraper = GitHubScraper(github_config, client)
    since = datetime.now(UTC) - timedelta(hours=24)
    items = await scraper.fetch(since)

    assert len(items) >= 1
    assert all(isinstance(i, ContentItem) for i in items)
    assert items[0].source_type == "github"
    assert "octocat" in items[0].author


@pytest.mark.anyio
async def test_github_scraper_empty_when_no_events(github_config):
    """GitHub scraper should return empty list when API returns no events."""
    from app.scrapers.github import GitHubScraper

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=[])
        return resp

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = mock_get

    scraper = GitHubScraper(github_config, client)
    since = datetime.now(UTC) - timedelta(hours=24)
    items = await scraper.fetch(since)
    assert items == []
