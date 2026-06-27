from unittest.mock import AsyncMock

import pytest

from app.api.routes import feed


@pytest.mark.anyio
async def test_manual_feeds_fetch_uses_configured_feeds(monkeypatch):
    expected = []
    monkeypatch.setattr(feed.settings, "RSS_FEEDS", ["https://example.com/feed.xml"])
    fetch_all = AsyncMock(return_value=expected)
    monkeypatch.setattr(feed, "fetch_all_feeds", fetch_all)

    result = await feed.manually_trigger_rss_fetch()

    assert result is expected
    fetch_all.assert_awaited_once_with(["https://example.com/feed.xml"])
