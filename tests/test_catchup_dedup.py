from unittest.mock import AsyncMock, patch

import pytest

from app.models.schemas import DailySummaryResponse, SummaryItem
from app.services.catchup_service import collect_catchup_news
from app.services.llm.catchup import CatchupMixin
from app.services.llm_service import llm_service


def _item(headline: str, url: str, source: str = "example") -> SummaryItem:
    return SummaryItem(
        headline=headline,
        category="AI",
        key_points=["k1"],
        original_link=url,
        source=source,
    )


def _summary(date: str, items: list[SummaryItem]) -> DailySummaryResponse:
    return DailySummaryResponse(
        date=date,
        overview=f"summary {date}",
        top_news=items,
    )


@pytest.mark.anyio
async def test_collect_catchup_news_excludes_articles_already_in_today():
    today_items = [_item("Today's lead", "https://example.com/article/")]
    earlier = _item("Earlier wording", "http://www.example.com/article#comments")
    unread = _item("Still unread", "https://example.com/other")

    with (
        patch(
            "app.services.catchup_service.db_service.get_unread_summary_items",
            new=AsyncMock(
                return_value=[
                    ("2026-06-08", _item("Today duplicate", "https://example.com/today")),
                    ("2026-06-07", earlier),
                    ("2026-06-07", unread),
                ]
            ),
        ),
        patch(
            "app.services.llm_service.llm_service.select_important_catchup_indices",
            new=AsyncMock(side_effect=lambda items: set(range(len(items)))),
        ),
    ):
        result = await collect_catchup_news(
            session=object(),
            board_id=1,
            catchup_days=7,
            today_str="2026-06-08",
            exclude_items=today_items,
            importance_selector=llm_service.select_important_catchup_indices,
        )

    assert [item.headline for item in result] == ["Still unread"]
    assert result[0].is_catchup is True
    assert result[0].original_date == "2026-06-07"


@pytest.mark.anyio
async def test_collect_catchup_news_deduplicates_history_items_by_normalized_url():
    old_variant = _item("Launch coverage", "https://example.com/shared-story")
    new_variant = _item("Shared story follow-up", "http://www.example.com/shared-story/")
    unique = _item("Unique catchup item", "https://example.com/unique-story")

    with (
        patch(
            "app.services.catchup_service.db_service.get_unread_summary_items",
            new=AsyncMock(
                return_value=[
                    ("2026-06-06", old_variant),
                    ("2026-06-07", new_variant),
                    ("2026-06-07", unique),
                ]
            ),
        ),
        patch(
            "app.services.llm_service.llm_service.select_important_catchup_indices",
            new=AsyncMock(side_effect=lambda items: set(range(len(items)))),
        ),
    ):
        result = await collect_catchup_news(
            session=object(),
            board_id=1,
            catchup_days=7,
            today_str="2026-06-08",
            importance_selector=llm_service.select_important_catchup_indices,
        )

    assert [item.headline for item in result] == [
        "Shared story follow-up",
        "Unique catchup item",
    ]


@pytest.mark.anyio
async def test_collect_catchup_news_deduplicates_by_cluster_id():
    today_items = [_item("Today's story", "https://example.com/today")]
    today_items[0].cluster_id = 42
    clustered = _item("Historical same event", "https://example.com/history")
    clustered.cluster_id = 42
    unique = _item("Different event", "https://example.com/different")
    unique.cluster_id = 77

    with (
        patch(
            "app.services.catchup_service.db_service.get_unread_summary_items",
            new=AsyncMock(
                return_value=[
                    ("2026-06-07", clustered),
                    ("2026-06-07", unique),
                ]
            ),
        ),
        patch(
            "app.services.llm_service.llm_service.select_important_catchup_indices",
            new=AsyncMock(side_effect=lambda items: set(range(len(items)))),
        ),
    ):
        result = await collect_catchup_news(
            session=object(),
            board_id=1,
            catchup_days=7,
            today_str="2026-06-08",
            exclude_items=today_items,
            importance_selector=llm_service.select_important_catchup_indices,
        )

    assert [item.headline for item in result] == ["Different event"]


def test_dedupe_catchup_summaries_keeps_newest_variant_of_same_url():
    summaries = [
        _summary(
            "2026-06-06",
            [_item("Launch coverage", "https://example.com/shared-story")],
        ).model_dump(),
        _summary(
            "2026-06-07",
            [
                SummaryItem(
                    headline="Launch coverage updated",
                    category="AI",
                    key_points=["k1", "k2", "k3"],
                    original_link="http://www.example.com/shared-story/",
                    source="example",
                ),
                _item("Unique catchup item", "https://example.com/unique-story"),
            ],
        ).model_dump(),
    ]

    deduped = CatchupMixin._dedupe_catchup_summaries(summaries)

    assert len(deduped) == 1
    assert deduped[0]["date"] == "2026-06-07"
    assert [item["headline"] for item in deduped[0]["top_news"]] == [
        "Launch coverage updated",
        "Unique catchup item",
    ]


@pytest.mark.anyio
async def test_score_catchup_items_uses_item_position_not_headline():
    mixin = CatchupMixin()
    mixin._score_flat_items = AsyncMock(return_value={0})
    summaries = [
        _summary(
            "2026-06-07",
            [
                _item("Same headline", "https://example.com/a"),
                _item("Same headline", "https://example.com/b"),
            ],
        ).model_dump()
    ]

    filtered = await mixin._score_catchup_items(summaries)

    assert len(filtered) == 1
    assert [item["original_link"] for item in filtered[0]["top_news"]] == ["https://example.com/a"]
