from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routes import sources


@pytest.mark.anyio
async def test_test_all_feeds_strips_sample_titles(monkeypatch):
    board = SimpleNamespace(id=1, slug="tech")
    monkeypatch.setattr(sources, "resolve_active_board", AsyncMock(return_value=board))
    monkeypatch.setattr(
        sources.db_service,
        "get_board_rss_feeds",
        AsyncMock(return_value=["https://example.com/feed.xml"]),
    )
    monkeypatch.setattr(
        sources,
        "check_single_feed_url",
        AsyncMock(
            return_value={
                "url": "https://example.com/feed.xml",
                "ok": True,
                "feed_title": "Example",
                "article_count": 3,
                "sample_titles": ["A", "B"],
            }
        ),
    )

    result = await sources.test_all_feeds(board="tech", session=object())

    assert result == [
        {
            "url": "https://example.com/feed.xml",
            "ok": True,
            "feed_title": "Example",
            "article_count": 3,
        }
    ]


@pytest.mark.anyio
async def test_source_coverage_resolves_board_and_delegates(monkeypatch):
    board = SimpleNamespace(id=7, slug="tech")
    expected = {"items": []}
    monkeypatch.setattr(sources, "resolve_active_board", AsyncMock(return_value=board))

    coverage = AsyncMock(return_value=expected)
    monkeypatch.setattr(
        "app.services.source_insights_service.get_source_coverage_analysis",
        coverage,
    )

    session = object()
    result = await sources.get_source_coverage_endpoint(
        board="tech",
        date="2026-06-26",
        days=3,
        limit=6,
        session=session,
    )

    assert result is expected
    coverage.assert_awaited_once_with(
        session,
        board_id=7,
        date="2026-06-26",
        days=3,
        limit=6,
    )
