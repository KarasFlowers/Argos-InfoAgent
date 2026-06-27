import httpx
import pytest

from app.api.routes import board_wizard as router
from app.api.routes.sources import check_single_feed_url, discover_feed_links


class _RedirectToLocalhostClient:
    def __init__(self):
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str, *, timeout: float, follow_redirects: bool):
        self.calls.append(url)
        assert follow_redirects is False
        return httpx.Response(
            status_code=302,
            headers={"location": "http://localhost:8000/private"},
            request=httpx.Request("GET", url),
        )


@pytest.mark.anyio
async def test_single_feed_blocks_localhost_before_fetch():
    result = await check_single_feed_url("http://localhost:8000/feed")

    assert result["ok"] is False
    assert "安全预检失败" in result["error"]


@pytest.mark.anyio
async def test_autodiscovery_blocks_localhost_before_fetch():
    feeds = await discover_feed_links("http://localhost:8000")

    assert feeds == []


@pytest.mark.anyio
async def test_probe_url_blocks_localhost_before_fetch():
    result = await router._probe_url(
        source_type="github",
        label="local",
        url="http://localhost:8000/api",
        timeout=1,
    )

    assert result["ok"] is False
    assert "安全预检失败" in result["error"]


@pytest.mark.anyio
async def test_autodiscovery_blocks_unsafe_redirect_before_following(monkeypatch):
    client = _RedirectToLocalhostClient()
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: client)

    feeds = await discover_feed_links("http://93.184.216.34")

    assert feeds == []
    assert client.calls == ["http://93.184.216.34"]
