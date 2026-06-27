from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import rss_service


class _FailingClient:
    async def get(self, url: str, timeout: float):
        raise AssertionError(f"HTTP client should not be called for unsafe URL: {url}")


class _RedirectToLocalhostClient:
    def __init__(self):
        self.calls: list[str] = []

    async def get(self, url: str, *, timeout: float, follow_redirects: bool):
        self.calls.append(url)
        assert follow_redirects is False
        return httpx.Response(
            status_code=302,
            headers={"location": "http://localhost:8000/private"},
            request=httpx.Request("GET", url),
        )


class _LargeFeedClient:
    async def get(self, url: str, *, timeout: float, follow_redirects: bool):
        return httpx.Response(
            status_code=200,
            content=b"x" * (rss_service.MAX_RSS_FEED_BYTES + 1),
            request=httpx.Request("GET", url),
        )


@pytest.mark.anyio
async def test_fetch_and_parse_feed_blocks_localhost_before_fetch(monkeypatch):
    monkeypatch.setattr(rss_service.redis_service, "get_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(rss_service, "_log_health", AsyncMock())

    result = await rss_service.fetch_and_parse_feed("http://localhost:8000/feed", _FailingClient())

    assert result is None
    rss_service._log_health.assert_awaited_once()
    _, kwargs = rss_service._log_health.await_args
    assert kwargs["status"] == "error"
    assert "localhost" in kwargs["error_message"]


@pytest.mark.anyio
async def test_fetch_and_parse_feed_rejects_oversized_response(monkeypatch):
    monkeypatch.setattr(rss_service.redis_service, "get_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(rss_service.redis_service, "set_cache", AsyncMock())
    monkeypatch.setattr(rss_service, "_log_health", AsyncMock())

    result = await rss_service.fetch_and_parse_feed("http://93.184.216.34/feed", _LargeFeedClient())

    assert result is None
    rss_service.redis_service.set_cache.assert_not_awaited()
    rss_service._log_health.assert_awaited_once()
    _, kwargs = rss_service._log_health.await_args
    assert kwargs["status"] == "error"
    assert "too large" in kwargs["error_message"]


@pytest.mark.anyio
async def test_fetch_and_parse_feed_blocks_unsafe_redirect_before_following(monkeypatch):
    monkeypatch.setattr(rss_service.redis_service, "get_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(rss_service, "_log_health", AsyncMock())
    client = _RedirectToLocalhostClient()

    result = await rss_service.fetch_and_parse_feed("http://93.184.216.34/feed", client)

    assert result is None
    assert client.calls == ["http://93.184.216.34/feed"]
    rss_service._log_health.assert_awaited_once()
    _, kwargs = rss_service._log_health.await_args
    assert kwargs["status"] == "error"
    assert "localhost" in kwargs["error_message"]
