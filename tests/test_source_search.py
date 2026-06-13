"""Unit tests for platform-native source search (Reddit / GitHub)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import source_search


def _fake_async_client(json_payload):
    """Build an httpx.AsyncClient stand-in whose .get() returns json_payload."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_payload)
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestSearchSubreddits:
    @pytest.mark.anyio
    async def test_parses_and_sorts_by_subscribers(self):
        payload = {"data": {"children": [
            {"data": {"display_name": "small", "title": "S", "subscribers": 100}},
            {"data": {"display_name": "big", "title": "B", "subscribers": 9000}},
        ]}}
        with patch("httpx.AsyncClient", return_value=_fake_async_client(payload)):
            out = await source_search.search_subreddits("machine learning")
        assert [s["name"] for s in out] == ["big", "small"]  # sorted desc
        assert out[0]["subscribers"] == 9000

    @pytest.mark.anyio
    async def test_empty_query_returns_empty(self):
        assert await source_search.search_subreddits("  ") == []

    @pytest.mark.anyio
    async def test_skips_entries_without_name(self):
        payload = {"data": {"children": [{"data": {"title": "no name"}}]}}
        with patch("httpx.AsyncClient", return_value=_fake_async_client(payload)):
            out = await source_search.search_subreddits("x")
        assert out == []

    @pytest.mark.anyio
    async def test_http_failure_returns_empty(self):
        client = _fake_async_client({})
        client.get = AsyncMock(side_effect=Exception("boom"))
        with patch("httpx.AsyncClient", return_value=client):
            out = await source_search.search_subreddits("x")
        assert out == []

    @pytest.mark.anyio
    async def test_respects_limit(self):
        children = [{"data": {"display_name": f"s{i}", "subscribers": i}} for i in range(20)]
        with patch("httpx.AsyncClient", return_value=_fake_async_client({"data": {"children": children}})):
            out = await source_search.search_subreddits("x", limit=3)
        assert len(out) == 3


class TestSearchGithubRepos:
    @pytest.mark.anyio
    async def test_parses_owner_repo_and_stars(self):
        payload = {"items": [
            {"full_name": "openai/whisper", "stargazers_count": 50000, "description": "ASR"},
            {"full_name": "bad-entry-no-slash", "stargazers_count": 1},
        ]}
        with patch("app.core.config.settings", MagicMock(GITHUB_TOKEN=None)), \
             patch("httpx.AsyncClient", return_value=_fake_async_client(payload)):
            out = await source_search.search_github_repos("whisper")
        assert out == [{"owner": "openai", "repo": "whisper", "stars": 50000, "description": "ASR"}]

    @pytest.mark.anyio
    async def test_adds_auth_header_when_token_present(self):
        client = _fake_async_client({"items": []})
        with patch("app.core.config.settings", MagicMock(GITHUB_TOKEN="ghp_x")), \
             patch("httpx.AsyncClient", return_value=client) as ctor:
            await source_search.search_github_repos("x")
        # token must be wired into the client headers
        headers = ctor.call_args.kwargs["headers"]
        assert headers["Authorization"] == "token ghp_x"

    @pytest.mark.anyio
    async def test_empty_query_returns_empty(self):
        assert await source_search.search_github_repos("") == []

    @pytest.mark.anyio
    async def test_http_failure_returns_empty(self):
        client = _fake_async_client({})
        client.get = AsyncMock(side_effect=Exception("boom"))
        with patch("app.core.config.settings", MagicMock(GITHUB_TOKEN=None)), \
             patch("httpx.AsyncClient", return_value=client):
            out = await source_search.search_github_repos("x")
        assert out == []
