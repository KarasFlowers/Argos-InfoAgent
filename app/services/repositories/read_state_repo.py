"""Article-level read-state repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.domain import ArticleReadState, DailySummary, NewsItem


class ReadStateRepo:
    async def get_read_state_map(
        self,
        session: AsyncSession,
        urls: list[str],
        board_id: int | None,
    ) -> dict[str, bool]:
        """Return {url: is_read}; missing rows are treated as unread by callers."""
        clean_urls = []
        for url in urls:
            clean_url = (url or "").strip()
            if clean_url and clean_url not in clean_urls:
                clean_urls.append(clean_url)
        if not clean_urls:
            return {}
        stmt = select(ArticleReadState).where(ArticleReadState.article_url.in_(clean_urls))
        if board_id is None:
            stmt = stmt.where(ArticleReadState.board_id.is_(None))
        else:
            stmt = stmt.where(ArticleReadState.board_id == board_id)
        result = await session.execute(stmt)
        return {row.article_url: bool(row.is_read) for row in result.scalars().all()}

    async def ensure_article_seen(
        self,
        session: AsyncSession,
        url: str,
        board_id: int | None,
    ) -> ArticleReadState | None:
        """Create or refresh an ArticleReadState row without marking it read."""
        url = (url or "").strip()
        if not url:
            return None
        now = datetime.now(UTC)
        stmt = select(ArticleReadState).where(ArticleReadState.article_url == url)
        if board_id is None:
            stmt = stmt.where(ArticleReadState.board_id.is_(None))
        else:
            stmt = stmt.where(ArticleReadState.board_id == board_id)
        result = await session.execute(stmt)
        row = result.scalars().first()
        if row:
            row.last_seen_at = now
            row.updated_at = now
            return row
        row = ArticleReadState(
            article_url=url,
            board_id=board_id,
            is_read=False,
            first_seen_at=now,
            last_seen_at=now,
            updated_at=now,
        )
        session.add(row)
        return row

    async def mark_article_read(
        self,
        session: AsyncSession,
        url: str,
        board_id: int | None,
        *,
        is_read: bool = True,
        commit: bool = True,
    ) -> None:
        row = await self.ensure_article_seen(session, url, board_id)
        if not row:
            return
        now = datetime.now(UTC)
        row.is_read = is_read
        row.read_at = now if is_read else None
        row.updated_at = now
        if commit:
            await session.commit()

    async def mark_summary_items_read(
        self,
        session: AsyncSession,
        items: list,
        board_id: int | None,
        *,
        commit: bool = True,
    ) -> None:
        for item in items:
            url = getattr(item, "original_link", "") or getattr(item, "article_url", "")
            if url:
                await self.mark_article_read(session, url, board_id, is_read=True, commit=False)
                if hasattr(item, "is_read"):
                    item.is_read = True
        if commit:
            await session.commit()

    async def get_unread_dates(
        self,
        session: AsyncSession,
        board_id: int | None,
        limit: int = 7,
    ) -> list[str]:
        board_match = or_(
            ArticleReadState.board_id == DailySummary.board_id,
            and_(ArticleReadState.board_id.is_(None), DailySummary.board_id.is_(None)),
        )
        stmt = (
            select(DailySummary.date)
            .join(NewsItem, NewsItem.summary_id == DailySummary.id)
            .outerjoin(
                ArticleReadState,
                and_(
                    ArticleReadState.article_url == NewsItem.original_link,
                    board_match,
                ),
            )
            .where(or_(ArticleReadState.id.is_(None), ArticleReadState.is_read.is_(False)))
            .where(NewsItem.original_link.is_not(None), NewsItem.original_link != "")
            .group_by(DailySummary.date)
            .order_by(DailySummary.date.desc())
            .limit(limit)
        )
        if board_id is not None:
            stmt = stmt.where(DailySummary.board_id == board_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def count_unread_articles_by_date(
        self,
        session: AsyncSession,
        board_id: int | None,
        limit: int = 14,
    ) -> dict[str, int]:
        dates = await self.get_unread_dates(session, board_id, limit=limit)
        if not dates:
            return {}
        counts: dict[str, int] = {}
        for date in dates:
            items = await self.get_unread_summary_items(session, board_id, days=limit, dates=[date])
            counts[date] = len(items)
        return counts

    async def get_unread_summary_items(
        self,
        session: AsyncSession,
        board_id: int | None,
        *,
        days: int = 7,
        dates: list[str] | None = None,
    ) -> list[tuple[str, NewsItem]]:
        board_match = or_(
            ArticleReadState.board_id == DailySummary.board_id,
            and_(ArticleReadState.board_id.is_(None), DailySummary.board_id.is_(None)),
        )
        stmt = (
            select(DailySummary.date, NewsItem)
            .join(NewsItem, NewsItem.summary_id == DailySummary.id)
            .outerjoin(
                ArticleReadState,
                and_(
                    ArticleReadState.article_url == NewsItem.original_link,
                    board_match,
                ),
            )
            .where(or_(ArticleReadState.id.is_(None), ArticleReadState.is_read.is_(False)))
            .where(NewsItem.original_link.is_not(None), NewsItem.original_link != "")
            .order_by(DailySummary.date.desc(), NewsItem.id.desc())
        )
        if board_id is not None:
            stmt = stmt.where(DailySummary.board_id == board_id)
        if dates is not None:
            stmt = stmt.where(DailySummary.date.in_(dates))
        else:
            cutoff = datetime.now().date()
            # SQLite dates are YYYY-MM-DD strings; string ordering matches date ordering.
            from datetime import timedelta

            stmt = stmt.where(DailySummary.date >= (cutoff - timedelta(days=days)).strftime("%Y-%m-%d"))
        result = await session.execute(stmt)
        return [(date, item) for date, item in result.all()]
