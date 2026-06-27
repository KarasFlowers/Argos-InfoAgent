"""
conftest.py - Shared fixtures for Argos tests.

Provides:
  - An async FastAPI test client via httpx.AsyncClient
  - Database initialization for test isolation
"""

import asyncio

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.background import cancel_all_background_tasks
from app.core.db import engine, init_db
from main import app


async def _dispose_test_engine() -> None:
    await engine.dispose()
    # aiosqlite closes its worker thread asynchronously; give its callback a
    # chance to land before pytest tears down the per-test event loop.
    await asyncio.sleep(0.05)


@pytest_asyncio.fixture
async def client():
    """Provide an async test client that talks directly to the ASGI app."""
    await _dispose_test_engine()
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await cancel_all_background_tasks()
    await _dispose_test_engine()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def dispose_db_engine_after_tests():
    yield
    await _dispose_test_engine()
