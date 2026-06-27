from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.routes import briefing


@pytest.mark.anyio
async def test_refine_briefing_returns_404_when_summary_missing(monkeypatch):
    board = SimpleNamespace(id=7)
    monkeypatch.setattr(briefing, "resolve_active_board", AsyncMock(return_value=board))
    monkeypatch.setattr(briefing.db_service, "get_summary_by_date", AsyncMock(return_value=None))

    payload = briefing.RefineRequest(date="2026-06-26", board="tech", instruction="Make it shorter")
    with pytest.raises(HTTPException) as exc_info:
        await briefing.refine_daily_briefing(payload=payload, session=object())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "No summary found for 2026-06-26 to refine."


@pytest.mark.anyio
async def test_daily_briefing_returns_sections(monkeypatch):
    board = SimpleNamespace(id=7, slug="tech")
    item = SimpleNamespace(
        headline="Headline",
        category="AI",
        key_points=["Point"],
        tags=["tag"],
        topic_path="AI/Models",
        original_link="https://example.com/a",
        source="Example",
        is_read=False,
        cluster_id=None,
    )
    summary = SimpleNamespace(
        date="2026-06-26",
        overview="Overview",
        perspective="overview",
        top_news=[item],
        stats_json={"sources": 1},
    )
    monkeypatch.setattr(briefing, "resolve_active_board", AsyncMock(return_value=board))
    monkeypatch.setattr(briefing.db_service, "get_summary_by_date", AsyncMock(return_value=summary))
    monkeypatch.setattr(briefing.db_service, "mark_article_read", AsyncMock())
    monkeypatch.setattr(briefing, "build_briefing_events", AsyncMock(return_value=[]))

    session = SimpleNamespace(commit=AsyncMock())
    payload = await briefing.get_daily_briefing(date="2026-06-26", board="tech", session=session)

    assert payload["date"] == "2026-06-26"
    assert payload["board"] == "tech"
    assert payload["sections"]["AI"][0]["headline"] == "Headline"
    assert payload["source_stats"] == {"sources": 1}
    assert payload["total_items"] == 1


@pytest.mark.anyio
async def test_get_refinement_session_serializes_result():
    created_at = datetime(2026, 6, 26, 8, 0, tzinfo=UTC)
    finished_at = datetime(2026, 6, 26, 8, 1, tzinfo=UTC)
    refinement = SimpleNamespace(
        id=3,
        board_id=7,
        date="2026-06-26",
        instruction="Make it shorter",
        status="done",
        refined_summary_json={"overview": "short"},
        error_message="",
        created_at=created_at,
        finished_at=finished_at,
    )
    result = SimpleNamespace(scalar_one_or_none=lambda: refinement)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    payload = await briefing.get_refinement_session(session_id=3, session=session)

    assert payload == {
        "session_id": 3,
        "board_id": 7,
        "date": "2026-06-26",
        "instruction": "Make it shorter",
        "status": "done",
        "refined_summary": {"overview": "short"},
        "error": None,
        "created_at": created_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
