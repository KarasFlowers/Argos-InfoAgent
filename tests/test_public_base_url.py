from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import main
from app.api.routes import feed
from app.core import db
from app.services.db_service import db_service


@pytest.mark.anyio
async def test_rss_feed_uses_public_base_url(monkeypatch):
    monkeypatch.setattr(feed.settings, "PUBLIC_BASE_URL", "https://argos.example/")
    monkeypatch.setattr(feed, "resolve_active_board", AsyncMock(return_value=None))
    monkeypatch.setattr(
        feed.db_service,
        "get_summary_history",
        AsyncMock(return_value=SimpleNamespace(archive_items=[])),
    )

    response = await feed.get_rss_feed(session=object())

    assert response.media_type == "application/rss+xml"
    assert "<link>https://argos.example</link>" in response.body.decode()


@pytest.mark.anyio
async def test_public_html_feed_uses_public_base_url(monkeypatch):
    captured_context = {}

    def fake_template_response(*, request, name, context):
        nonlocal captured_context
        captured_context = context
        return SimpleNamespace(request=request, name=name, context=context)

    monkeypatch.setattr(main.settings, "PUBLIC_BASE_URL", "https://argos.example/")
    monkeypatch.setattr(main.templates, "TemplateResponse", fake_template_response)

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = None
    monkeypatch.setattr(db, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(db_service, "get_default_board", AsyncMock(return_value=None))
    monkeypatch.setattr(db_service, "get_summary_by_date", AsyncMock(return_value=None))

    response = await main.public_feed(request=object(), date="2026-06-26")

    assert response.name == "feed.html"
    assert captured_context["canonical_url"] == "https://argos.example/feed?date=2026-06-26"
    assert captured_context["rss_url"] == "https://argos.example/api/v1/feed"
