from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.models.domain import Board, DailySummary, NewsItem, UserFeedback, UserPersona
from app.models.schemas import SummaryItem
from app.services.learning_service import (
    _get_article_text_for_urls,
    _normalize_feedback_url,
    get_inferred_interests,
    rerank_summary_items,
)
from app.services.persona_training_service import get_persona_training_summary


@pytest_asyncio.fixture
async def isolated_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


async def _make_board(session, slug: str) -> Board:
    board = Board(
        slug=slug,
        name=slug.title(),
        source_type="rss",
        source_config={"feeds": []},
    )
    session.add(board)
    await session.flush()
    return board


async def _make_summary_item(
    session,
    board_id: int,
    date: str,
    *,
    headline: str,
    url: str,
    source_name: str,
    category: str,
    tags: list[str],
):
    summary = DailySummary(
        date=date,
        board_id=board_id,
        perspective="overview",
        overview=f"Overview {date}",
    )
    session.add(summary)
    await session.flush()
    item = NewsItem(
        headline=headline,
        category=category,
        key_points=["k1"],
        tags=tags,
        topic_path=category,
        original_link=url,
        source=source_name,
        summary_id=summary.id,
    )
    session.add(item)
    await session.commit()
    return item


def test_normalize_feedback_url_rejects_blank_values():
    assert _normalize_feedback_url(" https://example.com/article ") == "https://example.com/article"
    with pytest.raises(ValueError):
        _normalize_feedback_url("   ")


@pytest.mark.anyio
async def test_get_inferred_interests_respects_board_scope_and_list_tags(isolated_session):
    board_a = await _make_board(isolated_session, "alpha")
    board_b = await _make_board(isolated_session, "beta")

    item_a = await _make_summary_item(
        isolated_session,
        board_a.id,
        "2026-06-08",
        headline="Agent tooling update",
        url="https://example.com/agents",
        source_name="Agent News",
        category="AI",
        tags=["agents", "llm"],
    )
    item_b = await _make_summary_item(
        isolated_session,
        board_b.id,
        "2026-06-08",
        headline="Crypto market update",
        url="https://example.com/crypto",
        source_name="Market News",
        category="Markets",
        tags=["crypto"],
    )

    isolated_session.add(UserFeedback(article_url=item_a.original_link, sentiment=1))
    isolated_session.add(UserFeedback(article_url=item_b.original_link, sentiment=1))
    await isolated_session.commit()

    interests = await get_inferred_interests(isolated_session, limit=6, board_id=board_a.id)
    names = {entry["name"] for entry in interests}

    assert "AI" in names
    assert "agents" in names
    assert "llm" in names
    assert "Markets" not in names
    assert "crypto" not in names


@pytest.mark.anyio
async def test_board_scoped_article_text_lookup_does_not_fallback_to_other_board_urls(isolated_session):
    board_a = await _make_board(isolated_session, "alpha")
    board_b = await _make_board(isolated_session, "beta")
    item_a = await _make_summary_item(
        isolated_session,
        board_a.id,
        "2026-06-08",
        headline="Agent tooling update",
        url="https://example.com/agents",
        source_name="Agent News",
        category="AI",
        tags=["agents"],
    )
    item_b = await _make_summary_item(
        isolated_session,
        board_b.id,
        "2026-06-08",
        headline="Crypto market update",
        url="https://example.com/crypto",
        source_name="Market News",
        category="Markets",
        tags=["crypto"],
    )

    texts = await _get_article_text_for_urls(
        isolated_session,
        [item_a.original_link, item_b.original_link, "https://example.com/not-in-board"],
        board_id=board_a.id,
    )

    assert len(texts) == 1
    assert "Agent tooling update" in texts[0]
    assert "Crypto market update" not in texts[0]


@pytest.mark.anyio
async def test_rerank_summary_items_uses_board_scoped_explicit_preferences(isolated_session):
    board_a = await _make_board(isolated_session, "alpha")
    board_b = await _make_board(isolated_session, "beta")
    isolated_session.add(UserPersona(content="crypto", category="block_topic", board_id=board_a.id))
    await isolated_session.commit()

    items = [
        SummaryItem(
            headline="Crypto market update",
            category="Markets",
            key_points=["Bitcoin moved sharply."],
            tags=["crypto"],
            original_link="https://example.com/crypto",
            source="Market News",
        ),
        SummaryItem(
            headline="LLM compiler update",
            category="AI",
            key_points=["Compiler support improved."],
            tags=["llm"],
            original_link="https://example.com/llm",
            source="AI News",
        ),
    ]

    board_a_items = await rerank_summary_items(
        [item.model_copy(deep=True) for item in items], session=isolated_session, board_id=board_a.id
    )
    board_b_items = await rerank_summary_items(
        [item.model_copy(deep=True) for item in items], session=isolated_session, board_id=board_b.id
    )

    assert [item.headline for item in board_a_items] == ["LLM compiler update"]
    assert [item.headline for item in board_b_items] == ["Crypto market update", "LLM compiler update"]


@pytest.mark.anyio
async def test_persona_training_summary_groups_feedback_and_preferences_by_board(isolated_session):
    board_a = await _make_board(isolated_session, "alpha")
    board_b = await _make_board(isolated_session, "beta")

    liked = await _make_summary_item(
        isolated_session,
        board_a.id,
        "2026-06-08",
        headline="LLM compiler update",
        url="https://example.com/compiler",
        source_name="Compiler Weekly",
        category="AI",
        tags=["llm", "compiler"],
    )
    disliked = await _make_summary_item(
        isolated_session,
        board_a.id,
        "2026-06-07",
        headline="Browser market share",
        url="https://example.com/browser",
        source_name="Browser Daily",
        category="Web",
        tags=["browser"],
    )
    other_board = await _make_summary_item(
        isolated_session,
        board_b.id,
        "2026-06-08",
        headline="Fintech snapshot",
        url="https://example.com/fintech",
        source_name="Fintech Wire",
        category="Finance",
        tags=["fintech"],
    )

    isolated_session.add(
        UserFeedback(
            article_url=liked.original_link,
            sentiment=1,
            created_at=datetime(2026, 6, 8, 8, 0, tzinfo=UTC),
        )
    )
    isolated_session.add(
        UserFeedback(
            article_url=disliked.original_link,
            sentiment=-1,
            created_at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
        )
    )
    isolated_session.add(
        UserFeedback(
            article_url=other_board.original_link,
            sentiment=1,
            created_at=datetime(2026, 6, 8, 10, 0, tzinfo=UTC),
        )
    )
    isolated_session.add(UserPersona(content="AI", category="focus_topic", board_id=board_a.id))
    isolated_session.add(UserPersona(content="Browser Daily", category="avoid_source", board_id=board_a.id))
    await isolated_session.commit()

    summary = await get_persona_training_summary(
        isolated_session,
        board_id=board_a.id,
        board_slug=board_a.slug,
        limit=5,
    )

    assert summary["board"] == "alpha"
    assert summary["feedback_summary"]["liked_count"] == 1
    assert summary["feedback_summary"]["disliked_count"] == 1
    assert summary["feedback_summary"]["focus_topic_count"] == 1
    assert summary["feedback_summary"]["avoid_source_count"] == 1
    assert [entry["name"] for entry in summary["top_sources"]] == ["Compiler Weekly"]
    assert len(summary["recent_feedback"]) == 2
    assert {entry["url"] for entry in summary["recent_feedback"]} == {
        liked.original_link,
        disliked.original_link,
    }
