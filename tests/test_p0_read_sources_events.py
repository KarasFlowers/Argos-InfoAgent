import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from sqlalchemy import Integer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select

from app.core.db import (
    _backfill_article_read_state,
    _ensure_legacy_columns,
    _migrate_phase2_schema,
    _sync_sources_from_board_configs,
)
from fastapi import HTTPException

from app.api.router import (
    _board_catchup_days,
    _build_briefing_events,
    _normalize_article_url_or_400,
    _normalize_source_url_or_400,
    _serialize_board,
    _validate_board_source_payload,
    get_rss_feed,
    get_catchup_status,
)
from app.models.domain import ArticleReadState, Board, ContentCluster, DailySummary, NewsItem, Source, SummaryViewLog, UserFeedback
from app.models.schemas import ContentItem, SummaryItem
from app.services.clustering_service import assign_clusters
from app.services.saved_service import _normalize_url as _normalize_saved_url
from app.services.source_adapters.multi_adapter import MultiSourceAdapter
from app.services.repositories import DBService


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


async def _make_board(session, slug: str, feeds: list[str] | None = None) -> Board:
    board = Board(
        slug=slug,
        name=slug.title(),
        source_type="rss",
        source_config={"feeds": feeds or []},
    )
    session.add(board)
    await session.flush()
    return board


async def _make_summary_with_item(
    session,
    board: Board,
    date: str,
    url: str,
    *,
    headline: str = "Shared story",
    cluster_id: int | None = None,
) -> NewsItem:
    summary = DailySummary(
        date=date,
        board_id=board.id,
        perspective="overview",
        overview=f"Overview {date}",
    )
    session.add(summary)
    await session.flush()
    item = NewsItem(
        headline=headline,
        category="AI",
        key_points=["k1"],
        tags=["tag"],
        topic_path="AI",
        original_link=url,
        source="Example",
        summary_id=summary.id,
        cluster_id=cluster_id,
    )
    session.add(item)
    await session.commit()
    return item


def test_board_catchup_days_column_is_integer():
    assert isinstance(Board.__table__.c.catchup_days.type, Integer)


def test_news_item_json_list_fields_use_default_factories():
    assert NewsItem.model_fields["key_points"].default_factory is list
    assert NewsItem.model_fields["tags"].default_factory is list


def test_source_url_normalizer_rejects_non_http_urls():
    assert _normalize_source_url_or_400(" https://example.com/feed.xml ") == "https://example.com/feed.xml"
    for raw_url in ["   ", "javascript:alert(1)", "ftp://example.com/feed.xml", "https:///missing-host"]:
        with pytest.raises(HTTPException):
            _normalize_source_url_or_400(raw_url)


def test_article_url_normalizers_reject_empty_but_allow_internal_urls():
    assert _normalize_article_url_or_400(" llm://board/date/1 ") == "llm://board/date/1"
    assert _normalize_saved_url(" https://example.com/article ") == "https://example.com/article"
    for normalizer in (_normalize_article_url_or_400, _normalize_saved_url):
        with pytest.raises((HTTPException, ValueError)):
            normalizer("   ")


def test_board_source_payload_rejects_invalid_rss_feed_urls():
    _validate_board_source_payload("rss", {"feeds": ["https://example.com/feed.xml"]})
    _validate_board_source_payload("multi", {"sources": {"rss": {"feeds": ["http://example.com/rss"]}}})

    for source_type, source_config in [
        ("rss", {"feeds": ["javascript:alert(1)"]}),
        ("multi", {"sources": {"rss": {"feeds": ["ftp://example.com/rss"]}}}),
        ("rss", {"feeds": [123]}),
    ]:
        with pytest.raises(HTTPException):
            _validate_board_source_payload(source_type, source_config)


@pytest.mark.anyio
async def test_legacy_startup_adds_integer_catchup_days_column():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE dailysummary (id INTEGER PRIMARY KEY, date TEXT)")
        await conn.exec_driver_sql("CREATE TABLE userpersona (id INTEGER PRIMARY KEY)")
        await conn.exec_driver_sql("CREATE TABLE board (id INTEGER PRIMARY KEY)")
        await conn.exec_driver_sql("CREATE TABLE newsitem (id INTEGER PRIMARY KEY)")

        await _ensure_legacy_columns(conn)

        columns = (await conn.exec_driver_sql("PRAGMA table_info(board)")).fetchall()

    await engine.dispose()

    catchup_column = next(row for row in columns if row[1] == "catchup_days")
    assert catchup_column[2].upper() == "INTEGER"


@pytest.mark.anyio
async def test_phase2_schema_migration_tolerates_duplicate_legacy_summaries():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE dailysummary (id INTEGER PRIMARY KEY, date TEXT, board_id INTEGER, perspective TEXT NOT NULL DEFAULT 'overview')"
        )
        await conn.exec_driver_sql("CREATE TABLE newsitem (id INTEGER PRIMARY KEY)")
        await conn.exec_driver_sql("CREATE TABLE board (id INTEGER PRIMARY KEY)")
        await conn.exec_driver_sql("CREATE TABLE userpersona (id INTEGER PRIMARY KEY)")
        await conn.exec_driver_sql(
            "INSERT INTO dailysummary (date, board_id, perspective) VALUES ('2026-06-08', 1, 'overview')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO dailysummary (date, board_id, perspective) VALUES ('2026-06-08', 1, 'overview')"
        )

        await _migrate_phase2_schema(conn)

    await engine.dispose()


@pytest.mark.anyio
async def test_board_repo_persists_catchup_days_as_int(isolated_session):
    db = DBService()
    board = await db.create_board(
        isolated_session,
        slug="catchup-days",
        name="Catchup Days",
        catchup_days=14,
    )

    assert board.catchup_days == 14
    assert isinstance(board.catchup_days, int)

    updated = await db.update_board(isolated_session, "catchup-days", {"catchup_days": 0})
    assert updated is not None
    assert updated.catchup_days == 0
    assert isinstance(updated.catchup_days, int)


@pytest.mark.anyio
async def test_board_catchup_days_zero_disables_status_window(isolated_session):
    board = await _make_board(isolated_session, "catchup-off")
    board.catchup_days = 0
    await isolated_session.commit()

    assert _board_catchup_days(board) == 0
    assert _serialize_board(board)["catchup_days"] == 0

    status = await get_catchup_status(
        board=board.slug,
        max_days=0,
        session=isolated_session,
    )
    assert status["catchup_days"] == 0
    assert status["unread_article_count"] == 0
    assert status["gap_count"] == 0


@pytest.mark.anyio
async def test_article_read_state_is_scoped_by_board(isolated_session):
    db = DBService()
    board_a = await _make_board(isolated_session, "alpha")
    board_b = await _make_board(isolated_session, "beta")
    url = "https://example.com/shared"
    await _make_summary_with_item(isolated_session, board_a, "2026-06-07", url)
    await _make_summary_with_item(isolated_session, board_b, "2026-06-07", url)

    await db.mark_article_read(isolated_session, url, board_a.id, is_read=True)

    unread_a = await db.get_unread_summary_items(isolated_session, board_a.id, dates=["2026-06-07"])
    unread_b = await db.get_unread_summary_items(isolated_session, board_b.id, dates=["2026-06-07"])

    assert unread_a == []
    assert len(unread_b) == 1
    assert unread_b[0][1].original_link == url


@pytest.mark.anyio
async def test_article_read_state_ignores_blank_urls(isolated_session):
    db = DBService()
    board = await _make_board(isolated_session, "blank-read-url")

    await db.mark_article_read(isolated_session, "   ", board.id, is_read=True)

    rows = (await isolated_session.execute(select(ArticleReadState))).scalars().all()
    assert rows == []


@pytest.mark.anyio
async def test_unread_state_ignores_items_without_article_url(isolated_session):
    db = DBService()
    board = await _make_board(isolated_session, "missing-links")
    summary = DailySummary(
        date="2026-06-07",
        board_id=board.id,
        perspective="overview",
        overview="Overview",
    )
    isolated_session.add(summary)
    await isolated_session.flush()

    readable = NewsItem(
        headline="Readable story",
        category="AI",
        key_points=["k1"],
        tags=["tag"],
        topic_path="AI",
        original_link="https://example.com/readable",
        source="Example",
        summary_id=summary.id,
    )
    no_link = NewsItem(
        headline="Generated note without URL",
        category="AI",
        key_points=["k2"],
        tags=["tag"],
        topic_path="AI",
        original_link="",
        source="Example",
        summary_id=summary.id,
    )
    isolated_session.add(readable)
    isolated_session.add(no_link)
    await isolated_session.commit()

    await db.mark_article_read(isolated_session, readable.original_link, board.id, is_read=True)

    unread = await db.get_unread_summary_items(isolated_session, board.id, dates=["2026-06-07"])
    view_map = await db.get_view_status_map(isolated_session, limit=3)

    assert unread == []
    assert view_map["2026-06-07"] is not None


@pytest.mark.anyio
async def test_cache_overview_is_scoped_by_board(isolated_session):
    db = DBService()
    board_a = await _make_board(isolated_session, "cache-alpha")
    board_b = await _make_board(isolated_session, "cache-beta")
    item_a = await _make_summary_with_item(
        isolated_session,
        board_a,
        "2026-06-07",
        "https://example.com/cache-a",
    )
    await _make_summary_with_item(
        isolated_session,
        board_b,
        "2026-06-07",
        "https://example.com/cache-b",
    )
    await db.mark_article_read(isolated_session, item_a.original_link, board_a.id, is_read=True)

    overview_a = await db.get_cache_overview(isolated_session, limit=5, board_id=board_a.id)
    overview_b = await db.get_cache_overview(isolated_session, limit=5, board_id=board_b.id)

    assert overview_a["total"] == 1
    assert overview_a["unviewed_count"] == 0
    assert overview_a["items"][0]["viewed_at"] is not None
    assert overview_b["total"] == 1
    assert overview_b["unviewed_count"] == 1
    assert overview_b["items"][0]["viewed_at"] is None


@pytest.mark.anyio
async def test_gap_dates_are_scoped_by_board(isolated_session):
    db = DBService()
    board_a = await _make_board(isolated_session, "gap-alpha")
    board_b = await _make_board(isolated_session, "gap-beta")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    isolated_session.add(DailySummary(
        date=yesterday,
        board_id=board_a.id,
        perspective="overview",
        overview="Board A already has this date.",
    ))
    await isolated_session.commit()

    gaps_a = await db.get_gap_dates(isolated_session, days=1, board_id=board_a.id)
    gaps_b = await db.get_gap_dates(isolated_session, days=1, board_id=board_b.id)

    assert yesterday not in gaps_a
    assert yesterday in gaps_b


@pytest.mark.anyio
async def test_rss_feed_endpoint_is_board_scoped(isolated_session):
    board_a = await _make_board(isolated_session, "feed-alpha")
    board_b = await _make_board(isolated_session, "feed-beta")
    await _make_summary_with_item(
        isolated_session,
        board_a,
        "2026-06-07",
        "https://example.com/feed-alpha",
        headline="Alpha only story",
    )
    await _make_summary_with_item(
        isolated_session,
        board_b,
        "2026-06-07",
        "https://example.com/feed-beta",
        headline="Beta only story",
    )

    response = await get_rss_feed(board=board_a.slug, session=isolated_session)
    body = response.body.decode("utf-8")

    assert "Feed-Alpha Daily Briefing" in body
    assert "Alpha only story" in body
    assert "Beta only story" not in body
    assert "argos-feed-alpha-2026-06-07" in body
    assert "board=feed-alpha" in body


@pytest.mark.anyio
async def test_cleanup_old_data_preserves_state_for_urls_still_referenced(isolated_session, monkeypatch):
    db = DBService()
    board = await _make_board(isolated_session, "cleanup-shared-url")
    shared_url = "https://example.com/shared-cleanup"
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    new_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    await _make_summary_with_item(isolated_session, board, old_date, shared_url, headline="Old copy")
    await _make_summary_with_item(isolated_session, board, new_date, shared_url, headline="New copy")
    await db.mark_article_read(isolated_session, shared_url, board.id, is_read=True)
    isolated_session.add(UserFeedback(article_url=shared_url, sentiment=1))
    await isolated_session.commit()

    deleted_rag_urls = []

    async def fake_delete_collections_by_urls(urls):
        deleted_rag_urls.extend(urls)

    monkeypatch.setattr("app.services.rag_service.delete_collections_by_urls", fake_delete_collections_by_urls)

    removed = await db.cleanup_old_data(isolated_session, days_to_keep=7)

    read_state = (await isolated_session.execute(
        select(ArticleReadState).where(ArticleReadState.article_url == shared_url)
    )).scalars().first()
    feedback = (await isolated_session.execute(
        select(UserFeedback).where(UserFeedback.article_url == shared_url)
    )).scalars().first()
    remaining_summaries = (await isolated_session.execute(
        select(DailySummary).where(DailySummary.date.in_([old_date, new_date]))
    )).scalars().all()

    assert removed == 1
    assert deleted_rag_urls == []
    assert read_state is not None
    assert feedback is not None
    assert [summary.date for summary in remaining_summaries] == [new_date]


@pytest.mark.anyio
async def test_summary_view_log_backfill_is_idempotent(isolated_session):
    board = await _make_board(isolated_session, "legacy")
    url = "https://example.com/legacy-read"
    await _make_summary_with_item(isolated_session, board, "2026-06-06", url)
    isolated_session.add(SummaryViewLog(date="2026-06-06"))
    await isolated_session.commit()

    conn = await isolated_session.connection()
    await _backfill_article_read_state(conn)
    await _backfill_article_read_state(conn)
    await isolated_session.commit()

    result = await isolated_session.execute(
        select(ArticleReadState).where(
            ArticleReadState.article_url == url,
            ArticleReadState.board_id == board.id,
        )
    )
    rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].is_read is True


@pytest.mark.anyio
async def test_source_sync_uses_source_table_and_mirrors_board_config(isolated_session):
    db = DBService()
    board = await _make_board(
        isolated_session,
        "rss-board",
        feeds=["https://a.example/feed.xml", "https://b.example/feed.xml", "https://a.example/feed.xml"],
    )

    await db.sync_board_rss_sources(isolated_session, board)
    assert await db.get_board_rss_feeds(isolated_session, board) == [
        "https://a.example/feed.xml",
        "https://b.example/feed.xml",
    ]

    added = await db.add_board_source(isolated_session, board, "https://c.example/feed.xml")
    assert added.enabled is True
    assert "https://c.example/feed.xml" in board.source_config["feeds"]

    await db.delete_board_source(isolated_session, board, added.id)
    assert await db.get_board_rss_feeds(isolated_session, board) == [
        "https://a.example/feed.xml",
        "https://b.example/feed.xml",
    ]
    assert "https://c.example/feed.xml" not in board.source_config["feeds"]


@pytest.mark.anyio
async def test_startup_source_config_sync_skips_invalid_legacy_urls(isolated_session):
    board = await _make_board(
        isolated_session,
        "legacy-invalid-feeds",
        feeds=[
            "https://valid.example/feed.xml",
            "javascript:alert(1)",
            "ftp://example.com/feed.xml",
        ],
    )
    await isolated_session.commit()

    conn = await isolated_session.connection()
    await _sync_sources_from_board_configs(conn)
    await isolated_session.commit()

    result = await isolated_session.execute(select(Source).where(Source.board_id == board.id))
    urls = [source.url for source in result.scalars().all()]

    assert urls == ["https://valid.example/feed.xml"]


@pytest.mark.anyio
async def test_source_repo_rejects_empty_source_url(isolated_session):
    db = DBService()
    board = await _make_board(isolated_session, "rss-empty-source")

    with pytest.raises(ValueError):
        await db.add_board_source(isolated_session, board, "   ")


@pytest.mark.anyio
async def test_source_repo_rejects_non_http_source_urls(isolated_session):
    db = DBService()
    board = await _make_board(
        isolated_session,
        "rss-invalid-source",
        feeds=["https://a.example/feed.xml"],
    )
    await db.sync_board_rss_sources(isolated_session, board)
    sources = await db.list_board_sources(isolated_session, board.id, "rss", enabled_only=True)

    with pytest.raises(ValueError):
        await db.add_board_source(isolated_session, board, "javascript:alert(1)")

    with pytest.raises(ValueError):
        await db.update_board_source(
            isolated_session,
            board,
            sources[0].id,
            url="ftp://example.com/feed.xml",
        )


@pytest.mark.anyio
async def test_source_update_can_set_manual_credibility_override(isolated_session):
    db = DBService()
    board = await _make_board(
        isolated_session,
        "rss-credibility",
        feeds=["https://a.example/feed.xml"],
    )
    await db.sync_board_rss_sources(isolated_session, board)
    sources = await db.list_board_sources(isolated_session, board.id, "rss", enabled_only=True)

    updated = await db.update_board_source(
        isolated_session,
        board,
        sources[0].id,
        credibility_override="official",
    )

    assert updated is not None
    assert updated.credibility_override == "official"


@pytest.mark.anyio
async def test_source_update_to_existing_url_disables_duplicate(isolated_session):
    db = DBService()
    board = await _make_board(
        isolated_session,
        "rss-dedupe-update",
        feeds=["https://a.example/feed.xml", "https://b.example/feed.xml"],
    )
    await db.sync_board_rss_sources(isolated_session, board)
    sources = await db.list_board_sources(isolated_session, board.id, "rss", enabled_only=True)

    updated = await db.update_board_source(
        isolated_session,
        board,
        sources[0].id,
        url=sources[1].url,
    )
    active = await db.list_board_sources(isolated_session, board.id, "rss", enabled_only=True)

    assert updated is not None
    assert [source.url for source in active] == ["https://b.example/feed.xml"]
    assert active[0].id == sources[0].id
    assert board.source_config["feeds"] == ["https://b.example/feed.xml"]


@pytest.mark.anyio
async def test_multi_adapter_uses_source_table_rss_without_legacy_rss_config(isolated_session, monkeypatch):
    board = Board(
        slug="multi-source-table-rss",
        name="Multi Source Table RSS",
        source_type="multi",
        source_config={"sources": {}},
    )
    isolated_session.add(board)
    await isolated_session.flush()
    isolated_session.add(Source(
        url="https://source-table.example/feed.xml",
        source_type="rss",
        enabled=True,
        board_id=board.id,
    ))
    await isolated_session.commit()

    seen: dict[str, object] = {}

    async def fake_fetch_rss(cfg):
        seen["feeds"] = cfg.get("feeds")
        return [ContentItem(
            id="rss:test:1",
            source_type="rss",
            title="Source table item",
            url="https://source-table.example/item",
            source_name="Source Table",
        )]

    async def fake_generate_daily_summary_from_items(items, **kwargs):
        seen["items"] = items
        seen["board"] = kwargs.get("board")
        return "summary", {}

    monkeypatch.setattr(MultiSourceAdapter, "_fetch_rss", staticmethod(fake_fetch_rss))
    monkeypatch.setattr(
        "app.services.llm_service.llm_service.generate_daily_summary_from_items",
        fake_generate_daily_summary_from_items,
    )

    summary, fallback = await MultiSourceAdapter().produce(board, isolated_session)

    assert summary == "summary"
    assert fallback == {}
    assert seen["feeds"] == ["https://source-table.example/feed.xml"]
    assert seen["items"][0].url == "https://source-table.example/item"
    assert seen["board"] is board


@pytest.mark.anyio
async def test_cluster_assignment_is_scoped_by_board(isolated_session):
    board_a = await _make_board(isolated_session, "cluster-alpha")
    board_b = await _make_board(isolated_session, "cluster-beta")
    item_a = await _make_summary_with_item(
        isolated_session,
        board_a,
        "2026-06-08",
        "https://example.com/a",
        headline="Shared event headline",
    )
    item_b = await _make_summary_with_item(
        isolated_session,
        board_b,
        "2026-06-08",
        "https://example.com/b",
        headline="Shared event headline",
    )

    await assign_clusters([item_a], board_a.id, isolated_session, commit=False)
    await assign_clusters([item_b], board_b.id, isolated_session, commit=False)
    await isolated_session.commit()

    clusters = (await isolated_session.execute(
        select(ContentCluster).where(ContentCluster.title == "Shared event headline")
    )).scalars().all()

    assert item_a.cluster_id is not None
    assert item_b.cluster_id is not None
    assert item_a.cluster_id != item_b.cluster_id
    assert {cluster.board_id for cluster in clusters} == {board_a.id, board_b.id}
    assert len({cluster.fingerprint for cluster in clusters}) == 2


@pytest.mark.anyio
async def test_briefing_events_include_recent_cluster_items(isolated_session):
    db = DBService()
    board = await _make_board(isolated_session, "events")
    cluster = ContentCluster(
        fingerprint="cluster-1",
        title="Same event",
        item_count=2,
        item_ids=[],
        board_id=board.id,
    )
    isolated_session.add(cluster)
    await isolated_session.flush()

    old_item = await _make_summary_with_item(
        isolated_session,
        board,
        "2026-06-07",
        "https://example.com/old",
        headline="Earlier event coverage",
        cluster_id=cluster.id,
    )
    new_item = await _make_summary_with_item(
        isolated_session,
        board,
        "2026-06-08",
        "https://example.com/new",
        headline="Latest event coverage",
        cluster_id=cluster.id,
    )
    cluster.item_ids = [old_item.id, new_item.id]
    await isolated_session.commit()

    await db.mark_article_read(isolated_session, new_item.original_link, board.id, is_read=True)
    root = SummaryItem(
        headline=new_item.headline,
        category=new_item.category,
        key_points=new_item.key_points,
        tags=new_item.tags,
        original_link=new_item.original_link,
        source=new_item.source,
        cluster_id=cluster.id,
    )

    events = await _build_briefing_events(isolated_session, board.id, [root], "2026-06-08")

    assert len(events) == 1
    assert events[0]["cluster_id"] == cluster.id
    assert events[0]["source_count"] == 1
    assert events[0]["days_covered"] == 2
    assert events[0]["unread_item_count"] == 1
    assert events[0]["first_date"] == "2026-06-07"
    assert events[0]["latest_date"] == "2026-06-08"
    assert [item["headline"] for item in events[0]["items"]] == [
        "Latest event coverage",
        "Earlier event coverage",
    ]
    assert events[0]["items"][0]["is_read"] is True


@pytest.mark.anyio
async def test_briefing_events_do_not_count_untrackable_items_as_unread(isolated_session):
    board = await _make_board(isolated_session, "events-no-link")
    cluster = ContentCluster(
        fingerprint="cluster-no-link",
        title="Untrackable event",
        item_count=1,
        item_ids=[],
        board_id=board.id,
    )
    isolated_session.add(cluster)
    await isolated_session.flush()

    item = await _make_summary_with_item(
        isolated_session,
        board,
        "2026-06-08",
        "",
        headline="LLM generated note",
        cluster_id=cluster.id,
    )
    cluster.item_ids = [item.id]
    await isolated_session.commit()

    root = SummaryItem(
        headline=item.headline,
        category=item.category,
        key_points=item.key_points,
        tags=item.tags,
        original_link=item.original_link,
        source=item.source,
        cluster_id=cluster.id,
    )

    events = await _build_briefing_events(isolated_session, board.id, [root], "2026-06-08")

    assert events[0]["unread_item_count"] == 0
    assert events[0]["items"][0]["is_read"] is True
