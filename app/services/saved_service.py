"""Saved articles service — favorites and read-later management.

Two independent statuses are supported (``favorite`` and ``read_later``) so the
same article URL can simultaneously be favorited and queued for later reading.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.db import AsyncSessionLocal
from app.models.domain import SavedArticle

logger = logging.getLogger(__name__)

VALID_STATUSES = ("favorite", "read_later")


def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got '{status}'.")


def _normalize_url(url: str) -> str:
    normalized = (url or "").strip()
    if not normalized:
        raise ValueError("article URL cannot be empty.")
    return normalized


async def add_saved(
    url: str,
    status: str,
    *,
    headline: str = "",
    source: str = "",
    category: str = "",
    board_slug: str = "",
) -> bool:
    """Add (idempotent upsert) a saved article for the given status."""
    _validate_status(status)
    url = _normalize_url(url)

    async with AsyncSessionLocal() as session:
        stmt = select(SavedArticle).where(
            SavedArticle.article_url == url,
            SavedArticle.status == status,
        )
        result = await session.execute(stmt)
        existing = result.scalars().first()

        if existing:
            # Refresh snapshot fields in case they changed.
            existing.headline = headline or existing.headline
            existing.source = source or existing.source
            existing.category = category or existing.category
            existing.board_slug = board_slug or existing.board_slug
        else:
            session.add(
                SavedArticle(
                    article_url=url,
                    status=status,
                    headline=headline,
                    source=source,
                    category=category,
                    board_slug=board_slug,
                )
            )
        await session.commit()
        return True


async def remove_saved(url: str, status: str) -> bool:
    """Remove a saved article for the given status. No-op if not present."""
    _validate_status(status)
    url = _normalize_url(url)

    async with AsyncSessionLocal() as session:
        stmt = select(SavedArticle).where(
            SavedArticle.article_url == url,
            SavedArticle.status == status,
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        for row in rows:
            await session.delete(row)
        await session.commit()
        return True


async def list_saved(status: str, limit: int = 200) -> list[dict]:
    """List saved articles for a status, newest first."""
    _validate_status(status)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(SavedArticle)
            .where(SavedArticle.status == status)
            .order_by(SavedArticle.created_at.desc(), SavedArticle.id.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "url": r.article_url,
                "status": r.status,
                "headline": r.headline,
                "source": r.source,
                "category": r.category,
                "board": r.board_slug,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


async def get_saved_url_map() -> dict[str, list[str]]:
    """Return a mapping of ``{article_url: [status, ...]}`` for frontend highlighting."""
    async with AsyncSessionLocal() as session:
        stmt = select(SavedArticle.article_url, SavedArticle.status)
        result = await session.execute(stmt)
        url_map: dict[str, list[str]] = {}
        for url, status in result.all():
            url_map.setdefault(url, []).append(status)
        return url_map
