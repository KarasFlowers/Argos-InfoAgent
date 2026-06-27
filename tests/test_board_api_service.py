from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.board_api_service import (
    board_supports_rss_sources,
    build_source_topic,
    serialize_board,
    serialize_source,
    validate_board_prompt_key_or_400,
    validate_board_source_payload,
)


def test_serialize_board_normalizes_defaults():
    board = SimpleNamespace(
        id=1,
        slug="ai",
        name="AI",
        icon="",
        description="",
        system_prompt="",
        source_type="rss",
        source_config=None,
        perspectives=None,
        prompt_key="",
        output_language="",
        schedule=None,
        notify_channels=None,
        display_order=0,
        is_active=True,
        is_default=False,
        catchup_days=0,
    )

    payload = serialize_board(board)

    assert payload["source_config"] == {}
    assert payload["perspectives"] == {}
    assert payload["prompt_key"] == "daily_briefing"
    assert payload["output_language"] == "auto"
    assert payload["catchup_days"] == 0


def test_serialize_source_normalizes_optional_fields():
    source = SimpleNamespace(
        id=3,
        url="https://example.com/feed.xml",
        name=None,
        source_type="rss",
        enabled=1,
        board_id=2,
        last_fetched_at=None,
        created_at=None,
    )

    payload = serialize_source(source)

    assert payload["name"] == ""
    assert payload["site_url"] == ""
    assert payload["enabled"] is True
    assert payload["health_status"] == "unknown"


def test_build_source_topic_uses_board_context_and_fallback():
    board = SimpleNamespace(name="AI", description="Research", system_prompt="Track papers")

    assert build_source_topic(board, "arXiv") == "AI Research Track papers arXiv"
    assert build_source_topic(SimpleNamespace(), "") == "通用资讯"


def test_board_supports_rss_source_management_only_for_rss_and_multi():
    assert board_supports_rss_sources(SimpleNamespace(source_type="rss")) is True
    assert board_supports_rss_sources(SimpleNamespace(source_type="multi")) is True
    assert board_supports_rss_sources(SimpleNamespace(source_type="github")) is False
    assert board_supports_rss_sources(None) is False


def test_validate_board_source_payload_rejects_unsafe_rss_urls():
    validate_board_source_payload("rss", {"feeds": ["https://example.com/feed.xml"]})
    validate_board_source_payload("multi", {"sources": {"rss": {"feeds": ["https://example.com/rss"]}}})

    for source_type, source_config in [
        ("rss", {"feeds": ["javascript:alert(1)"]}),
        ("multi", {"sources": {"rss": {"feeds": ["ftp://example.com/rss"]}}}),
        ("rss", {"feeds": [123]}),
    ]:
        with pytest.raises(HTTPException):
            validate_board_source_payload(source_type, source_config)


def test_validate_board_prompt_key_or_400_normalizes_and_rejects_unknown_keys():
    assert validate_board_prompt_key_or_400(None) == "daily_briefing"

    with pytest.raises(HTTPException):
        validate_board_prompt_key_or_400("does-not-exist")
