"""Unit tests for the RSS discovery fallback chain (Stage 3).

Covers:
  - _probe_common_feed_paths: probes /feed, /rss, ... when autodiscovery is empty
  - _rsshub_candidate_urls: builds RSSHub URLs from planner platform identifiers
  - _discover_rss_candidates: falls back to common paths + RSSHub
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes import board_wizard as router


class TestProbeCommonFeedPaths:
    @pytest.mark.anyio
    async def test_returns_reachable_paths(self):
        async def fake_test(url, timeout=6.0):
            return {"url": url, "ok": url.endswith("/feed")}

        with patch("app.api.routes.board_wizard._test_single_feed", side_effect=fake_test):
            out = await router._probe_common_feed_paths("https://blog.example.com/posts")
        assert out == ["https://blog.example.com/feed"]

    @pytest.mark.anyio
    async def test_strips_path_to_root(self):
        seen = []

        async def fake_test(url, timeout=6.0):
            seen.append(url)
            return {"url": url, "ok": False}

        with patch("app.api.routes.board_wizard._test_single_feed", side_effect=fake_test):
            await router._probe_common_feed_paths("https://x.com/a/b/c?q=1")
        # all probes must hit the host root, not the deep path
        assert all(u.startswith("https://x.com/") and "/a/b/c" not in u for u in seen)

    @pytest.mark.anyio
    async def test_invalid_url_returns_empty(self):
        assert await router._probe_common_feed_paths("not-a-url") == []
        assert await router._probe_common_feed_paths("") == []

    @pytest.mark.anyio
    async def test_respects_limit(self):
        async def fake_test(url, timeout=6.0):
            return {"url": url, "ok": True}  # everything reachable

        with patch("app.api.routes.board_wizard._test_single_feed", side_effect=fake_test):
            out = await router._probe_common_feed_paths("https://x.com", limit=2)
        assert len(out) == 2


class TestRsshubCandidateUrls:
    def test_builds_from_platform_entries(self):
        plan = {
            "candidates": {
                "rsshub": [
                    {"platform": "bilibili_user_video", "uid": "2267573"},
                    {"platform": "jike_user", "id": "ABC"},
                ]
            }
        }
        with (
            patch("app.api.routes.board_wizard.settings", MagicMock(RSSHUB_ENABLED=True)),
            patch("app.services.rsshub._base_url", return_value="https://rsshub.app"),
        ):
            urls = router._rsshub_candidate_urls(plan)
        assert "https://rsshub.app/bilibili/user/video/2267573" in urls
        assert "https://rsshub.app/jike/user/ABC" in urls

    def test_skips_unknown_platform(self):
        plan = {"candidates": {"rsshub": [{"platform": "bogus", "id": "x"}]}}
        with patch("app.api.routes.board_wizard.settings", MagicMock(RSSHUB_ENABLED=True)):
            assert router._rsshub_candidate_urls(plan) == []

    def test_disabled_returns_empty(self):
        plan = {"candidates": {"rsshub": [{"platform": "jike_user", "id": "ABC"}]}}
        with patch("app.api.routes.board_wizard.settings", MagicMock(RSSHUB_ENABLED=False)):
            assert router._rsshub_candidate_urls(plan) == []

    def test_no_rsshub_entries_returns_empty(self):
        with patch("app.api.routes.board_wizard.settings", MagicMock(RSSHUB_ENABLED=True)):
            assert router._rsshub_candidate_urls({"candidates": {}}) == []


class TestDiscoverRssCandidatesFallback:
    @pytest.mark.anyio
    async def test_falls_back_to_common_paths_when_autodiscovery_empty(self):
        plan = {"search_terms": [], "homepage_hints": ["https://zhihu.com"], "candidates": {}}
        with (
            patch("app.api.routes.board_wizard.tavily_search", AsyncMock(return_value=[]), create=True),
            patch("app.services.research_service.tavily_search", AsyncMock(return_value=[])),
            patch("app.api.routes.board_wizard._discover_feeds", AsyncMock(return_value=[])),
            patch(
                "app.api.routes.board_wizard._probe_common_feed_paths",
                AsyncMock(return_value=["https://zhihu.com/feed"]),
            ),
            patch("app.api.routes.board_wizard._rsshub_candidate_urls", return_value=[]),
        ):
            feeds = await router._discover_rss_candidates(plan)
        assert feeds == ["https://zhihu.com/feed"]

    @pytest.mark.anyio
    async def test_includes_rsshub_urls(self):
        plan = {"search_terms": [], "homepage_hints": [], "candidates": {}}
        with (
            patch("app.services.research_service.tavily_search", AsyncMock(return_value=[])),
            patch(
                "app.api.routes.board_wizard._rsshub_candidate_urls", return_value=["https://rsshub.app/jike/user/X"]
            ),
        ):
            feeds = await router._discover_rss_candidates(plan)
        assert "https://rsshub.app/jike/user/X" in feeds

    @pytest.mark.anyio
    async def test_skips_common_probe_when_autodiscovery_succeeds(self):
        plan = {"search_terms": [], "homepage_hints": ["https://blog.com"], "candidates": {}}
        probe = AsyncMock(return_value=["should-not-appear"])
        with (
            patch("app.services.research_service.tavily_search", AsyncMock(return_value=[])),
            patch("app.api.routes.board_wizard._discover_feeds", AsyncMock(return_value=["https://blog.com/atom"])),
            patch("app.api.routes.board_wizard._probe_common_feed_paths", probe),
            patch("app.api.routes.board_wizard._rsshub_candidate_urls", return_value=[]),
        ):
            feeds = await router._discover_rss_candidates(plan)
        assert feeds == ["https://blog.com/atom"]
        probe.assert_not_called()  # homepage already advertised a feed
