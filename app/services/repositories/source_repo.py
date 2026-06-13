"""Repository helpers for board-scoped RSS sources."""
from __future__ import annotations

from datetime import datetime, UTC
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.domain import Board, Source


def _rss_feeds_from_config(source_type: str, source_config: dict | None) -> list[str]:
    cfg = source_config or {}
    if source_type == "rss":
        return [u.strip() for u in (cfg.get("feeds") or []) if isinstance(u, str) and u.strip()]
    if source_type == "multi":
        rss_cfg = (cfg.get("sources") or {}).get("rss") or {}
        return [u.strip() for u in (rss_cfg.get("feeds") or []) if isinstance(u, str) and u.strip()]
    return []


def _with_rss_feeds_in_config(source_type: str, source_config: dict | None, feeds: list[str]) -> dict:
    cfg = dict(source_config or {})
    if source_type == "rss":
        cfg["feeds"] = feeds
    elif source_type == "multi":
        sources = dict(cfg.get("sources") or {})
        rss_cfg = dict(sources.get("rss") or {})
        rss_cfg["feeds"] = feeds
        sources["rss"] = rss_cfg
        cfg["sources"] = sources
    return cfg


def _unique_urls(urls: list[str]) -> list[str]:
    unique: list[str] = []
    for url in urls:
        if not isinstance(url, str) or not url.strip():
            continue
        normalized = _require_source_url(url)
        if normalized not in unique:
            unique.append(normalized)
    return unique


def _require_source_url(url: str) -> str:
    normalized = (url or "").strip()
    parsed = urlparse(normalized)
    if not normalized or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Source URL must be a valid http(s) URL.")
    return normalized


class SourceRepo:
    async def list_board_sources(
        self,
        session: AsyncSession,
        board_id: int,
        source_type: str = "rss",
        enabled_only: bool = False,
    ) -> list[Source]:
        stmt = select(Source).where(Source.board_id == board_id, Source.source_type == source_type)
        if enabled_only:
            stmt = stmt.where(Source.enabled == True)
        stmt = stmt.order_by(Source.id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_board_rss_feeds(self, session: AsyncSession, board: Board) -> list[str]:
        sources = await self.list_board_sources(session, board.id, "rss", enabled_only=True) if board.id else []
        urls = [s.url for s in sources if s.url]
        if urls:
            return urls
        return _rss_feeds_from_config(board.source_type, board.source_config)

    async def sync_board_rss_sources(
        self,
        session: AsyncSession,
        board: Board,
        feeds: list[str] | None = None,
        *,
        commit: bool = True,
    ) -> Board:
        if not board.id:
            return board
        feed_urls = feeds if feeds is not None else _rss_feeds_from_config(board.source_type, board.source_config)
        normalized = _unique_urls(feed_urls)

        existing = await self.list_board_sources(session, board.id, "rss", enabled_only=False)
        existing_by_url: dict[str, Source] = {}
        duplicate_ids: set[int] = set()
        for source in existing:
            if source.url in existing_by_url:
                if source.id is not None:
                    duplicate_ids.add(source.id)
            else:
                existing_by_url[source.url] = source
        now = datetime.now(UTC)
        for url in normalized:
            source = existing_by_url.get(url)
            if source:
                source.enabled = True
            else:
                session.add(Source(url=url, source_type="rss", enabled=True, board_id=board.id, created_at=now))
        for source in existing:
            if source.url not in normalized or source.id in duplicate_ids:
                source.enabled = False

        board.source_config = _with_rss_feeds_in_config(board.source_type, board.source_config, normalized)
        if commit:
            await session.commit()
            await session.refresh(board)
        return board

    async def add_board_source(
        self,
        session: AsyncSession,
        board: Board,
        url: str,
        *,
        name: str = "",
        credibility_override: str = "",
    ) -> Source:
        url = _require_source_url(url)
        feeds = await self.get_board_rss_feeds(session, board)
        if url not in feeds:
            feeds.append(url)
        await self.sync_board_rss_sources(session, board, feeds, commit=False)
        stmt = select(Source).where(Source.board_id == board.id, Source.source_type == "rss", Source.url == url)
        result = await session.execute(stmt)
        source = result.scalars().first()
        if source and name:
            source.name = name
        if source and credibility_override.strip():
            source.credibility_override = credibility_override.strip()
        await session.commit()
        if source:
            await session.refresh(source)
            return source
        result = await session.execute(stmt)
        source = result.scalars().first()
        if not source:
            raise ValueError("Failed to create source row.")
        return source

    async def update_board_source(
        self,
        session: AsyncSession,
        board: Board,
        source_id: int,
        *,
        url: str | None = None,
        name: str | None = None,
        enabled: bool | None = None,
        credibility_override: str | None = None,
    ) -> Source | None:
        stmt = select(Source).where(Source.id == source_id, Source.board_id == board.id, Source.source_type == "rss")
        result = await session.execute(stmt)
        source = result.scalars().first()
        if not source:
            return None
        if url is not None:
            normalized_url = _require_source_url(url)
            if normalized_url and normalized_url != source.url:
                dup_stmt = select(Source).where(
                    Source.board_id == board.id,
                    Source.source_type == "rss",
                    Source.url == normalized_url,
                    Source.id != source.id,
                )
                dup_result = await session.execute(dup_stmt)
                for duplicate in dup_result.scalars().all():
                    duplicate.enabled = False
            source.url = normalized_url
        if name is not None:
            source.name = name
        if enabled is not None:
            source.enabled = enabled
        if credibility_override is not None:
            source.credibility_override = credibility_override.strip()
        await session.flush()
        active = _unique_urls([s.url for s in await self.list_board_sources(session, board.id, "rss", enabled_only=True)])
        board.source_config = _with_rss_feeds_in_config(board.source_type, board.source_config, active)
        await session.commit()
        await session.refresh(source)
        return source

    async def delete_board_source(self, session: AsyncSession, board: Board, source_id: int) -> bool:
        stmt = select(Source).where(Source.id == source_id, Source.board_id == board.id, Source.source_type == "rss")
        result = await session.execute(stmt)
        source = result.scalars().first()
        if not source:
            return False
        source.enabled = False
        await session.flush()
        active = _unique_urls([s.url for s in await self.list_board_sources(session, board.id, "rss", enabled_only=True)])
        board.source_config = _with_rss_feeds_in_config(board.source_type, board.source_config, active)
        await session.commit()
        return True
