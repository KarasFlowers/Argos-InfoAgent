from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.routes import history


@pytest.mark.anyio
async def test_summary_history_clamps_limit_and_resolves_board(monkeypatch):
    board = SimpleNamespace(id=42)
    expected = SimpleNamespace(archive_items=[])
    session = object()
    monkeypatch.setattr(history, "resolve_active_board", AsyncMock(return_value=board))
    monkeypatch.setattr(history.db_service, "get_summary_history", AsyncMock(return_value=expected))

    result = await history.get_summary_history(limit=999, board="tech", session=session)

    assert result is expected
    history.db_service.get_summary_history.assert_awaited_once_with(session, limit=30, board_id=42)


@pytest.mark.anyio
async def test_weekly_insight_returns_404_when_no_history(monkeypatch):
    board = SimpleNamespace(id=42, output_language="zh")
    monkeypatch.setattr(history, "resolve_active_board", AsyncMock(return_value=board))
    monkeypatch.setattr(
        history.db_service, "get_summary_history", AsyncMock(return_value=SimpleNamespace(archive_items=[]))
    )

    with pytest.raises(HTTPException) as exc_info:
        await history.get_weekly_insight(limit=7, board="tech", session=object())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "No history found to summarize."


@pytest.mark.anyio
async def test_cache_overview_without_board_skips_board_resolution(monkeypatch):
    expected = {"items": []}
    session = object()
    resolve = AsyncMock()
    monkeypatch.setattr(history, "resolve_active_board", resolve)
    monkeypatch.setattr(history.db_service, "get_cache_overview", AsyncMock(return_value=expected))

    result = await history.get_cache_overview(limit=0, board=None, session=session)

    assert result is expected
    resolve.assert_not_called()
    history.db_service.get_cache_overview.assert_awaited_once_with(session, limit=1, board_id=None)
