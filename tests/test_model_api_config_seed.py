import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.db import _seed_default_model_api_configs


@pytest.mark.anyio
async def test_model_api_config_seed_does_not_persist_env_api_keys(monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-secret")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://api.example/v1")
    monkeypatch.setattr(settings, "LLM_MODEL", "model-default")
    monkeypatch.setattr(settings, "FAST_LLM", "fast-model")
    monkeypatch.setattr(settings, "SMART_LLM", "smart-model")

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE modelapiconfig (
                id INTEGER PRIMARY KEY,
                name TEXT,
                base_url TEXT,
                api_key TEXT,
                model_name TEXT,
                concurrency INTEGER,
                is_active BOOLEAN,
                created_at TIMESTAMP
            )
            """
        )
        await _seed_default_model_api_configs(conn)
        rows = (
            await conn.exec_driver_sql("SELECT name, api_key, model_name FROM modelapiconfig ORDER BY name")
        ).fetchall()

    await engine.dispose()

    assert rows
    assert all(row[1] == "" for row in rows)
