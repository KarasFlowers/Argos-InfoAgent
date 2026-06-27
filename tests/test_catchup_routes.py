from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routes import catchup


@pytest.mark.anyio
async def test_catchup_status_zero_days_short_circuits(monkeypatch):
    board = SimpleNamespace(id=7, catchup_days=0)
    monkeypatch.setattr(catchup, "resolve_active_board", AsyncMock(return_value=board))
    monkeypatch.setattr(catchup.db_service, "get_unread_summary_items", AsyncMock())
    monkeypatch.setattr(catchup.db_service, "get_gap_dates", AsyncMock())

    payload = await catchup.get_catchup_status(board="tech", session=object())

    assert payload["catchup_days"] == 0
    assert payload["unread_article_count"] == 0
    catchup.db_service.get_unread_summary_items.assert_not_called()
    catchup.db_service.get_gap_dates.assert_not_called()


@pytest.mark.anyio
async def test_generate_catchup_digest_returns_empty_message_when_no_unread(monkeypatch):
    board = SimpleNamespace(id=7, slug="tech", source_type="rss", output_language="zh")
    monkeypatch.setattr(catchup, "resolve_active_board", AsyncMock(return_value=board))
    monkeypatch.setattr(catchup.db_service, "get_gap_dates", AsyncMock(return_value=[]))
    monkeypatch.setattr(catchup.db_service, "get_unread_summary_items", AsyncMock(return_value=[]))

    payload = await catchup.generate_catchup_digest(board="tech", max_days=7, session=object())

    assert payload == {
        "digest": None,
        "dates_covered": [],
        "backfilled_dates": [],
        "total_items": 0,
        "message": "No unread content to digest.",
    }
