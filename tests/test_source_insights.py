from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.models.domain import ContentCluster, DailySummary, NewsItem, Source
from app.api import router
from app.services.source_insights_service import (
    annotate_source_validation,
    get_source_coverage_analysis,
    prioritize_source_candidates,
    review_source_candidates,
)


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


async def _make_board(session, slug: str):
    from app.models.domain import Board

    board = Board(slug=slug, name=slug.title(), source_type="rss", source_config={"feeds": []})
    session.add(board)
    await session.commit()
    await session.refresh(board)
    return board


async def _make_summary_item(
    session,
    board_id: int,
    date: str,
    *,
    headline: str,
    url: str,
    source_name: str,
    cluster_id: int | None = None,
    tags: list[str] | None = None,
    key_points: list[str] | None = None,
):
    summary_stmt = select(DailySummary).where(
        DailySummary.board_id == board_id,
        DailySummary.date == date,
        DailySummary.perspective == "overview",
    )
    summary = (await session.execute(summary_stmt)).scalar_one_or_none()
    if not summary:
        summary = DailySummary(date=date, board_id=board_id, overview=f"Overview {date}", perspective="overview")
        session.add(summary)
        await session.flush()
    item = NewsItem(
        headline=headline,
        category="AI",
        key_points=key_points or ["k1"],
        tags=tags or ["ai"],
        topic_path="AI",
        original_link=url,
        source=source_name,
        cluster_id=cluster_id,
        summary_id=summary.id,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@pytest.mark.anyio
async def test_source_coverage_analysis_summarizes_different_angles(isolated_session):
    board = await _make_board(isolated_session, "coverage")
    cluster = ContentCluster(fingerprint="cluster-coverage", title="Model release", item_count=3, item_ids=[], board_id=board.id)
    isolated_session.add(cluster)
    await isolated_session.commit()
    await isolated_session.refresh(cluster)

    first = await _make_summary_item(
        isolated_session,
        board.id,
        "2026-06-08",
        headline="Model release focuses on speed",
        url="https://example.com/speed",
        source_name="Fast Source",
        cluster_id=cluster.id,
        tags=["model", "release", "speed"],
        key_points=["Coverage highlights inference speed and latency."],
    )
    second = await _make_summary_item(
        isolated_session,
        board.id,
        "2026-06-08",
        headline="Model release focuses on safety",
        url="https://example.org/safety",
        source_name="Safety Source",
        cluster_id=cluster.id,
        tags=["model", "release", "safety"],
        key_points=["Coverage highlights safeguards and eval quality."],
    )
    cluster.item_ids = [first.id, second.id]
    await isolated_session.commit()

    analysis = await get_source_coverage_analysis(
        isolated_session,
        board_id=board.id,
        date="2026-06-08",
        days=3,
        limit=5,
    )

    assert analysis["items"]
    item = analysis["items"][0]
    assert item["cluster_id"] == cluster.id
    assert item["source_count"] == 2
    assert len(item["source_angles"]) == 2
    assert item["difference_summary"]


@pytest.mark.anyio
async def test_source_coverage_endpoint_filters_by_board_and_date(isolated_session):
    board = await _make_board(isolated_session, "coverage-endpoint")
    other_board = await _make_board(isolated_session, "coverage-other")
    primary_cluster = ContentCluster(
        fingerprint="cluster-endpoint-primary",
        title="Primary release",
        item_count=2,
        item_ids=[],
        board_id=board.id,
    )
    secondary_cluster = ContentCluster(
        fingerprint="cluster-endpoint-secondary",
        title="Secondary release",
        item_count=2,
        item_ids=[],
        board_id=other_board.id,
    )
    isolated_session.add(primary_cluster)
    isolated_session.add(secondary_cluster)
    await isolated_session.commit()
    await isolated_session.refresh(primary_cluster)
    await isolated_session.refresh(secondary_cluster)

    first = await _make_summary_item(
        isolated_session,
        board.id,
        "2026-06-08",
        headline="Primary release emphasizes performance",
        url="https://primary.example/perf",
        source_name="Primary Source A",
        cluster_id=primary_cluster.id,
        tags=["release", "performance"],
        key_points=["This outlet focused on inference throughput."],
    )
    second = await _make_summary_item(
        isolated_session,
        board.id,
        "2026-06-08",
        headline="Primary release emphasizes safety",
        url="https://primary.example/safety",
        source_name="Primary Source B",
        cluster_id=primary_cluster.id,
        tags=["release", "safety"],
        key_points=["This outlet focused on guardrails and evaluations."],
    )
    primary_cluster.item_ids = [first.id, second.id]

    other_first = await _make_summary_item(
        isolated_session,
        other_board.id,
        "2026-06-08",
        headline="Other board coverage about cost",
        url="https://other.example/cost",
        source_name="Other Source A",
        cluster_id=secondary_cluster.id,
        tags=["release", "cost"],
        key_points=["This board covered price and deployment cost."],
    )
    other_second = await _make_summary_item(
        isolated_session,
        other_board.id,
        "2026-06-08",
        headline="Other board coverage about ecosystem",
        url="https://other.example/ecosystem",
        source_name="Other Source B",
        cluster_id=secondary_cluster.id,
        tags=["release", "ecosystem"],
        key_points=["This board covered partnerships and integrations."],
    )
    secondary_cluster.item_ids = [other_first.id, other_second.id]
    await isolated_session.commit()

    payload = await router.get_source_coverage_endpoint(
        board=board.slug,
        date="2026-06-08",
        days=3,
        limit=10,
        session=isolated_session,
    )

    assert payload["date"] == "2026-06-08"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["cluster_id"] == primary_cluster.id
    assert payload["items"][0]["title"] == "Primary release"


def test_annotate_source_validation_adds_trust_metadata():
    annotated = annotate_source_validation(
        [
            {
                "source_type": "rss",
                "url": "https://example.com/feed.xml",
                "ok": True,
                "article_count": 8,
                "sample_titles": ["a", "b", "c"],
            }
        ]
    )

    assert annotated[0]["trust_score"] > 0
    assert annotated[0]["trust_label"] in {"high", "medium", "watch", "risky"}
    assert "quality_summary" in annotated[0]


def test_prioritize_source_candidates_drops_risky_when_safe_pool_is_large():
    ranked = prioritize_source_candidates(
        [
            {"url": "https://safe-a.example/feed", "trust_label": "high", "trust_score": 88, "article_count": 4, "ok": True},
            {"url": "https://safe-b.example/feed", "trust_label": "medium", "trust_score": 76, "article_count": 3, "ok": True},
            {"url": "https://safe-c.example/feed", "trust_label": "watch", "trust_score": 55, "article_count": 2, "ok": True},
            {"url": "http://risky.example/feed", "trust_label": "risky", "trust_score": 22, "article_count": 6, "ok": True},
        ]
    )

    assert [entry["url"] for entry in ranked] == [
        "https://safe-a.example/feed",
        "https://safe-b.example/feed",
        "https://safe-c.example/feed",
    ]


def test_review_source_candidates_reports_why_risky_entries_were_dropped():
    report = review_source_candidates(
        [
            {"url": "https://safe-a.example/feed", "trust_label": "high", "trust_score": 88, "article_count": 4, "ok": True, "quality_summary": "Trusted publication."},
            {"url": "https://safe-b.example/feed", "trust_label": "medium", "trust_score": 71, "article_count": 3, "ok": True, "quality_summary": "Stable coverage."},
            {"url": "https://safe-c.example/feed", "trust_label": "watch", "trust_score": 51, "article_count": 2, "ok": True, "quality_summary": "Monitor quality."},
            {"url": "http://risky.example/feed", "trust_label": "risky", "trust_score": 22, "article_count": 6, "ok": True, "quality_summary": "No HTTPS and poor signals."},
        ]
    )

    assert len(report["selected"]) == 3
    assert len(report["dropped"]) == 1
    assert "filtered out" in report["summary"]
    assert "Dropped because safer verified sources were already available." in report["dropped"][0]["selection_reason"]


def test_review_source_candidates_does_not_count_failed_sources_as_safe():
    report = review_source_candidates(
        [
            {"url": "https://safe-a.example/feed", "trust_label": "medium", "trust_score": 70, "article_count": 0, "ok": False},
            {"url": "https://safe-b.example/feed", "trust_label": "medium", "trust_score": 68, "article_count": 0, "ok": False},
            {"url": "http://risky.example/feed", "trust_label": "risky", "trust_score": 22, "article_count": 5, "ok": True},
        ],
        min_non_risky=2,
    )

    assert report["safe_count"] == 0
    assert [entry["url"] for entry in report["selected"]] == ["http://risky.example/feed"]
    assert {entry["url"] for entry in report["dropped"]} == {
        "https://safe-a.example/feed",
        "https://safe-b.example/feed",
    }


@pytest.mark.anyio
async def test_source_alternatives_endpoint_returns_ranked_replacements(isolated_session):
    board = await _make_board(isolated_session, "remediate")
    source = Source(
        url="http://risky.example/feed.xml",
        name="Risky Feed",
        source_type="rss",
        enabled=True,
        board_id=board.id,
        health_status="unhealthy",
        last_error="timeout",
    )
    isolated_session.add(source)
    await isolated_session.commit()
    await isolated_session.refresh(source)

    async def fake_test_feed(url: str, timeout: float = 8.0):
        return {
            "url": url,
            "ok": True,
            "article_count": 5 if "safe-a" in url else 3,
            "feed_title": "Replacement Feed",
            "sample_titles": ["One", "Two", "Three"],
        }

    with patch.object(router.llm_service, "suggest_alternative_feeds", AsyncMock(return_value=[
        {"original": source.url, "suggestions": ["https://safe-a.example/feed", "http://risky-b.example/feed"]},
    ])), patch.object(router, "_test_single_feed", side_effect=fake_test_feed):
        payload = await router.get_board_source_alternatives_endpoint(
            board.slug,
            source.id,
            session=isolated_session,
        )

    assert payload["source"]["id"] == source.id
    assert payload["alternatives"][0]["url"] == "https://safe-a.example/feed"
    assert payload["alternatives"][0]["trust_label"] in {"high", "medium", "watch"}
    assert payload["summary"]


@pytest.mark.anyio
async def test_source_discovery_endpoint_skips_existing_sources_and_returns_new_candidates(isolated_session):
    board = await _make_board(isolated_session, "discover")
    existing = Source(
        url="https://existing.example/feed.xml",
        name="Existing Feed",
        source_type="rss",
        enabled=True,
        board_id=board.id,
        health_status="healthy",
    )
    isolated_session.add(existing)
    await isolated_session.commit()
    await isolated_session.refresh(existing)

    plan = {
        "ready": True,
        "source_type": "rss",
        "search_terms": ["agent news"],
        "homepage_hints": ["https://new.example"],
        "candidates": {},
    }
    verified = [
        {
            "source_type": "rss",
            "url": "https://existing.example/feed.xml",
            "ok": True,
            "article_count": 4,
            "feed_title": "Existing Feed",
            "sample_titles": ["Existing story"],
        },
        {
            "source_type": "rss",
            "url": "https://new.example/feed.xml",
            "ok": True,
            "article_count": 7,
            "feed_title": "New Feed",
            "sample_titles": ["Fresh story", "Second story"],
        },
    ]

    with patch.object(router.llm_service, "wizard_plan_sources", AsyncMock(return_value=plan)), \
         patch.object(router, "_discover_rss_candidates", AsyncMock(return_value=[entry["url"] for entry in verified])), \
         patch.object(router, "_verify_and_fix_feeds", AsyncMock(return_value=verified)):
        payload = await router.discover_board_sources_endpoint(
            board.slug,
            router.BoardSourceDiscoverRequest(query="agent news", limit=5),
            session=isolated_session,
        )

    assert payload["searched_terms"][0] == "agent news"
    assert payload["skipped_existing"] == ["https://existing.example/feed.xml"]
    assert len(payload["suggestions"]) == 1
    assert payload["suggestions"][0]["url"] == "https://new.example/feed.xml"
