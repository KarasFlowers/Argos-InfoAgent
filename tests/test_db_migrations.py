import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.core.db as db
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.config import settings
from app.models import domain as _domain_models  # noqa: F401


@pytest.fixture
async def isolated_db(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "argos.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "AsyncSessionLocal", session_factory)
    try:
        yield engine, session_factory
    finally:
        await engine.dispose()


async def _columns(conn, table_name: str) -> set[str]:
    rows = await conn.exec_driver_sql(f"PRAGMA table_info({table_name})")
    return {row[1] for row in rows.fetchall()}


async def _tables(conn) -> set[str]:
    rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    return {row[0] for row in rows.fetchall()}


@pytest.mark.asyncio
async def test_init_db_bootstraps_empty_sqlite_database(isolated_db):
    engine, _ = isolated_db

    await db.init_db()

    async with engine.connect() as conn:
        tables = await _tables(conn)
        assert {"board", "source", "modelapiconfig", "taskrun", "savedarticle"}.issubset(tables)

        board_count = (await conn.execute(text("SELECT COUNT(*) FROM board"))).scalar_one()
        source_count = (await conn.execute(text("SELECT COUNT(*) FROM source"))).scalar_one()
        model_config_count = (await conn.execute(text("SELECT COUNT(*) FROM modelapiconfig"))).scalar_one()

    assert board_count == 1
    assert source_count >= 1
    assert model_config_count == 1


@pytest.mark.asyncio
async def test_init_db_upgrades_legacy_sqlite_schema(isolated_db):
    engine, _ = isolated_db
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE board (
                id INTEGER PRIMARY KEY,
                slug VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                icon VARCHAR NOT NULL DEFAULT '',
                description VARCHAR NOT NULL DEFAULT '',
                system_prompt VARCHAR NOT NULL DEFAULT '',
                source_type VARCHAR NOT NULL DEFAULT 'rss',
                source_config VARCHAR,
                display_order INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                is_default BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO board
                (slug, name, source_config, created_at)
            VALUES
                ('legacy', 'Legacy', '{"feeds":["https://example.com/feed.xml"]}', CURRENT_TIMESTAMP)
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE dailysummary (
                id INTEGER PRIMARY KEY,
                date VARCHAR NOT NULL,
                overview VARCHAR NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE userpersona (
                id INTEGER PRIMARY KEY,
                content VARCHAR NOT NULL,
                category VARCHAR NOT NULL DEFAULT 'instruction',
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE newsitem (
                id INTEGER PRIMARY KEY,
                headline VARCHAR NOT NULL,
                category VARCHAR NOT NULL,
                key_points VARCHAR,
                tags VARCHAR,
                original_link VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                summary_id INTEGER NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE source (
                id INTEGER PRIMARY KEY,
                url VARCHAR NOT NULL,
                name VARCHAR NOT NULL DEFAULT '',
                site_url TEXT NOT NULL DEFAULT '',
                source_type VARCHAR NOT NULL DEFAULT 'rss',
                enabled BOOLEAN NOT NULL DEFAULT 1,
                board_id INTEGER,
                health_status TEXT NOT NULL DEFAULT 'healthy',
                last_fetched_at DATETIME,
                last_error TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO source (url, created_at)
            VALUES ('https://example.com/feed.xml', CURRENT_TIMESTAMP)
            """
        )

    await db.init_db()

    async with engine.connect() as conn:
        assert {
            "schedule",
            "notify_channels",
            "catchup_days",
            "perspectives",
            "prompt_key",
            "output_language",
        }.issubset(await _columns(conn, "board"))
        assert {"stats_json", "board_id", "perspective"}.issubset(await _columns(conn, "dailysummary"))
        assert {"board_id", "weight", "source", "last_refreshed"}.issubset(await _columns(conn, "userpersona"))
        assert {"topic_path", "cluster_id"}.issubset(await _columns(conn, "newsitem"))
        assert "credibility_override" in await _columns(conn, "source")

        legacy_board = (
            await conn.execute(
                text(
                    "SELECT schedule, notify_channels, catchup_days, prompt_key, output_language "
                    "FROM board WHERE slug = 'legacy'"
                )
            )
        ).one()
        source_result = await conn.execute(
            text("SELECT credibility_override FROM source WHERE url = 'https://example.com/feed.xml'")
        )
        legacy_sources = source_result.scalars().all()

    assert legacy_board == ("", "", 7, "daily_briefing", "auto")
    assert set(legacy_sources) == {""}


def test_alembic_revision_graph_has_single_head():
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["c9f1d2e3a4b5"]


def test_alembic_upgrade_head_bootstraps_empty_sqlite_database(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "alembic-head.db"
    monkeypatch.setattr(settings, "SQLALCHEMY_DATABASE_URI", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    model_tables = {table_name: set(table.columns.keys()) for table_name, table in SQLModel.metadata.tables.items()}

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        db_columns = {
            table_name: {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")} for table_name in tables
        }

    assert {"board", "source", "modelapiconfig", "taskrun", "savedarticle"}.issubset(tables)
    missing_tables = set(model_tables) - tables
    missing_columns = {
        table_name: sorted(columns - db_columns.get(table_name, set()))
        for table_name, columns in model_tables.items()
        if columns - db_columns.get(table_name, set())
    }
    assert missing_tables == set()
    assert missing_columns == {}
    assert version == "c9f1d2e3a4b5"
