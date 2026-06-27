import pytest

from app.models.schemas import DailySummaryResponse, SummaryItem
from app.services.recommendation_explain import enrich_summary_explanations, explain_item


def _item(**overrides) -> SummaryItem:
    data = {
        "headline": "New local LLM benchmark",
        "category": "AI",
        "key_points": ["A new benchmark compares open models."],
        "tags": ["LLM", "benchmark"],
        "original_link": "https://example.com/llm",
        "source": "Compiler Weekly",
    }
    data.update(overrides)
    return SummaryItem(**data)


def test_explain_item_uses_fallback_reason_without_preferences():
    item = explain_item(_item(), {})

    assert item.preference_matches == []
    assert item.recommendation_reason
    assert item.assistant_questions


def test_explain_item_surfaces_explicit_preferences():
    item = explain_item(
        _item(persona_score=0.42),
        {
            "focus_topic": ["LLM"],
            "block_topic": [],
            "prefer_source": ["Compiler Weekly"],
            "avoid_source": [],
        },
    )

    assert "关注话题：LLM" in item.preference_matches
    assert "优先来源：Compiler Weekly" in item.preference_matches
    assert "匹配你的关注话题" in item.recommendation_reason


def test_explain_item_marks_fallback_without_claiming_quality():
    item = explain_item(
        _item(persona_score=0.42),
        {"focus_topic": ["LLM"], "prefer_source": ["Compiler Weekly"]},
        is_fallback=True,
    )

    assert item.preference_matches == []
    assert item.recommendation_reason == "AI 摘要暂时不可用，当前仅按原始来源展示"


@pytest.mark.anyio
async def test_enrich_summary_explanations_handles_cached_and_catchup_items(monkeypatch):
    async def fake_prefs(session, board_id=None):
        return {
            "focus_topic": ["benchmark"],
            "block_topic": [],
            "prefer_source": [],
            "avoid_source": [],
        }

    monkeypatch.setattr(
        "app.services.recommendation_explain.db_service.get_explicit_preferences",
        fake_prefs,
    )
    summary = DailySummaryResponse(
        date="2026-06-27",
        overview="Overview",
        top_news=[_item()],
        catchup_news=[_item(headline="Catchup", original_link="https://example.com/catchup")],
    )

    enriched = await enrich_summary_explanations(summary, session=object(), board_id=1)

    assert enriched.top_news[0].recommendation_reason
    assert enriched.catchup_news[0].preference_matches == ["关注话题：benchmark"]
