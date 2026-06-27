"""Summary repository — read/write operations for DailySummary + NewsItem."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, desc, func, or_
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.domain import (
    ArticleOverview,
    ArticleReadState,
    ChatMessage,
    DailySummary,
    NewsItem,
    UserFeedback,
)
from app.models.schemas import (
    DailySummaryResponse,
    HistoryStatItem,
    SummaryArchiveItem,
    SummaryHistoryResponse,
    SummaryItem,
    WeeklyRecapResponse,
)

logger = logging.getLogger(__name__)


class SummaryRepo:
    async def get_summary_by_date(
        self,
        session: AsyncSession,
        date_str: str,
        board_id: int | None = None,
        perspective: str = "overview",
    ) -> DailySummaryResponse | None:
        statement = select(DailySummary).where(
            DailySummary.date == date_str,
            DailySummary.perspective == perspective,
        )
        if board_id is not None:
            statement = statement.where(DailySummary.board_id == board_id)
        result = await session.execute(statement)
        db_summary = result.scalars().first()

        if not db_summary:
            return None

        news_statement = select(NewsItem).where(NewsItem.summary_id == db_summary.id)
        news_result = await session.execute(news_statement)
        db_news_items = news_result.scalars().all()

        article_urls = [item.original_link for item in db_news_items]
        feedback_map: dict[str, int] = {}
        read_map: dict[str, bool] = {}
        if article_urls:
            feedback_statement = select(UserFeedback.article_url, UserFeedback.sentiment).where(
                UserFeedback.article_url.in_(article_urls)
            )
            feedback_result = await session.execute(feedback_statement)
            feedback_map = dict(feedback_result.all())
            read_stmt = select(ArticleReadState.article_url, ArticleReadState.is_read).where(
                ArticleReadState.article_url.in_(article_urls)
            )
            if board_id is None:
                read_stmt = read_stmt.where(ArticleReadState.board_id.is_(None))
            else:
                read_stmt = read_stmt.where(ArticleReadState.board_id == board_id)
            read_result = await session.execute(read_stmt)
            read_map = {url: bool(is_read) for url, is_read in read_result.all()}

        top_news = []
        for item in db_news_items:
            # key_points and tags are native JSON columns (list type)
            key_points_list = item.key_points if isinstance(item.key_points, list) else []
            tags_list = item.tags if isinstance(item.tags, list) else []

            top_news.append(
                SummaryItem(
                    headline=item.headline,
                    category=item.category or "Uncategorized",
                    key_points=key_points_list,
                    tags=tags_list,
                    topic_path=item.topic_path or "",
                    original_link=item.original_link,
                    source=item.source,
                    feedback_sentiment=feedback_map.get(item.original_link),
                    is_read=read_map.get(item.original_link, False),
                    cluster_id=item.cluster_id,
                )
            )

        stats = {}
        for item in top_news:
            stats[item.source] = stats.get(item.source, 0) + 1

        return DailySummaryResponse(
            date=db_summary.date,
            overview=db_summary.overview,
            perspective=db_summary.perspective or "overview",
            top_news=top_news,
            source_stats=stats,
            recommendation_report=db_summary.stats_json if isinstance(db_summary.stats_json, dict) else {},
        )

    async def get_recent_article_urls(
        self,
        session: AsyncSession,
        board_id: int | None = None,
        days: int = 3,
    ) -> set[str]:
        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        stmt = select(DailySummary.id).where(DailySummary.date >= cutoff, DailySummary.date < today)
        if board_id is not None:
            stmt = stmt.where(DailySummary.board_id == board_id)
        result = await session.execute(stmt)
        summary_ids = list(result.scalars().all())
        if not summary_ids:
            return set()
        news_stmt = select(NewsItem.original_link).where(NewsItem.summary_id.in_(summary_ids))
        news_result = await session.execute(news_stmt)
        return set(news_result.scalars().all())

    async def get_summary_archive(
        self, session: AsyncSession, limit: int = 7, board_id: int | None = None
    ) -> list[SummaryArchiveItem]:
        history = await self.get_summary_history(session, limit=limit, board_id=board_id)
        return history.archive_items

    async def get_summary_history(
        self, session: AsyncSession, limit: int = 7, board_id: int | None = None
    ) -> SummaryHistoryResponse:
        statement = select(DailySummary)
        if board_id is not None:
            statement = statement.where(DailySummary.board_id == board_id)
        statement = statement.order_by(desc(DailySummary.date)).limit(limit)
        result = await session.execute(statement)
        summaries = result.scalars().all()

        if not summaries:
            return SummaryHistoryResponse()

        summary_ids = [summary.id for summary in summaries if summary.id is not None]
        news_by_summary_id: dict[int, list[NewsItem]] = {summary_id: [] for summary_id in summary_ids}

        if summary_ids:
            news_statement = select(NewsItem).where(NewsItem.summary_id.in_(summary_ids))
            news_result = await session.execute(news_statement)
            for item in news_result.scalars().all():
                news_by_summary_id.setdefault(item.summary_id, []).append(item)

        archive: list[SummaryArchiveItem] = []
        source_totals: dict[str, int] = {}
        category_totals: dict[str, int] = {}

        for summary in summaries:
            news_items = news_by_summary_id.get(summary.id or -1, [])
            source_stats: dict[str, int] = {}
            category_counts: dict[str, int] = {}

            for item in news_items:
                source = item.source or "未知来源"
                category = item.category or "未分类"
                source_stats[source] = source_stats.get(source, 0) + 1
                category_counts[category] = category_counts.get(category, 0) + 1
                source_totals[source] = source_totals.get(source, 0) + 1
                category_totals[category] = category_totals.get(category, 0) + 1

            top_categories = [
                name
                for name, _ in sorted(
                    category_counts.items(),
                    key=lambda pair: (-pair[1], pair[0]),
                )[:3]
            ]

            overview_preview = (summary.overview or "").strip().replace("\n", " ")
            if len(overview_preview) > 120:
                overview_preview = overview_preview[:117].rstrip() + "..."

            archive.append(
                SummaryArchiveItem(
                    date=summary.date,
                    overview_preview=overview_preview,
                    news_count=len(news_items),
                    source_stats=source_stats,
                    top_categories=top_categories,
                )
            )

        weekly_recap = self._build_weekly_recap(archive, category_totals, source_totals)
        return SummaryHistoryResponse(archive_items=archive, weekly_recap=weekly_recap)

    def _build_weekly_recap(
        self,
        archive_items: list[SummaryArchiveItem],
        category_totals: dict[str, int],
        source_totals: dict[str, int],
    ) -> WeeklyRecapResponse | None:
        if not archive_items:
            return None

        sorted_categories = sorted(category_totals.items(), key=lambda pair: (-pair[1], pair[0]))
        sorted_sources = sorted(source_totals.items(), key=lambda pair: (-pair[1], pair[0]))
        top_category_names = [name for name, _ in sorted_categories[:3]]
        latest_entry = archive_items[0]
        previous_entry = archive_items[1] if len(archive_items) > 1 else None

        recap_parts = []
        if top_category_names:
            recap_parts.append(f"本周主要聚焦 {', '.join(top_category_names)}")
        if sorted_sources:
            recap_parts.append(f"其中 {sorted_sources[0][0]} 出现最频繁")
        if previous_entry:
            latest_categories = set(latest_entry.top_categories)
            previous_categories = set(previous_entry.top_categories)
            new_categories = [category for category in latest_categories if category not in previous_categories]
            if new_categories:
                recap_parts.append(f"最新一期新增了 {', '.join(new_categories[:2])} 等主题")
            elif latest_categories & previous_categories:
                recurring = list(latest_categories & previous_categories)
                recap_parts.append(f"最近两期持续关注 {', '.join(recurring[:2])}")

        recap_text = "，".join(recap_parts) + "。" if recap_parts else "本周已有多期简报，可从这里快速回看重点主题。"

        return WeeklyRecapResponse(
            window_start=archive_items[-1].date,
            window_end=archive_items[0].date,
            days_covered=len(archive_items),
            total_news=sum(item.news_count for item in archive_items),
            top_categories=[HistoryStatItem(name=name, count=count) for name, count in sorted_categories[:3]],
            top_sources=[HistoryStatItem(name=name, count=count) for name, count in sorted_sources[:3]],
            recap_text=recap_text,
            latest_date=archive_items[0].date,
        )

    async def replace_summary(
        self,
        session: AsyncSession,
        summary: DailySummaryResponse,
        board_id: int | None = None,
    ) -> None:
        try:
            perspective = summary.perspective or "overview"
            statement = select(DailySummary).where(
                DailySummary.date == summary.date,
                DailySummary.perspective == perspective,
            )
            if board_id is not None:
                statement = statement.where(DailySummary.board_id == board_id)
            result = await session.execute(statement)
            existing = result.scalars().first()

            if existing:
                await session.execute(sa_delete(NewsItem).where(NewsItem.summary_id == existing.id))
                await session.delete(existing)
                await session.flush()

            await self._persist_summary(session, summary, board_id=board_id)
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise

    async def save_summary(
        self,
        session: AsyncSession,
        summary: DailySummaryResponse,
        board_id: int | None = None,
    ) -> None:
        try:
            await self._persist_summary(session, summary, board_id=board_id)
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise

    async def _persist_summary(
        self,
        session: AsyncSession,
        summary: DailySummaryResponse,
        board_id: int | None = None,
    ) -> None:
        db_summary = DailySummary(
            date=summary.date,
            board_id=board_id,
            perspective=summary.perspective or "overview",
            overview=summary.overview,
            stats_json=summary.recommendation_report if summary.recommendation_report else None,
        )
        session.add(db_summary)
        await session.flush()

        persisted_news: list[NewsItem] = []
        for item in summary.top_news:
            db_news = NewsItem(
                headline=item.headline,
                category=item.category,
                key_points=item.key_points if isinstance(item.key_points, list) else [],
                tags=item.tags if isinstance(item.tags, list) else [],
                topic_path=item.topic_path or "",
                original_link=item.original_link,
                source=item.source,
                summary_id=db_summary.id,
            )
            session.add(db_news)
            persisted_news.append(db_news)

        await session.flush()

        for item in persisted_news:
            if hasattr(self, "ensure_article_seen"):
                await self.ensure_article_seen(session, item.original_link, board_id)

        try:
            from app.services.clustering_service import assign_clusters

            await assign_clusters(persisted_news, board_id=board_id, session=session, commit=False)
        except Exception as exc:
            logger.debug("Cluster assignment skipped for %s: %s", summary.date, exc)

    async def get_available_dates(self, session: AsyncSession, limit: int = 7) -> list[str]:
        statement = select(DailySummary.date).order_by(desc(DailySummary.date)).limit(limit)
        result = await session.execute(statement)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Viewed tracking (catch-up / digest)
    # ------------------------------------------------------------------

    async def mark_date_viewed(self, session: AsyncSession, date_str: str) -> None:
        """Compatibility shim: mark all articles in a summary date as read."""
        stmt = select(DailySummary).where(DailySummary.date == date_str)
        result = await session.execute(stmt)
        summaries = list(result.scalars().all())
        for summary in summaries:
            news_result = await session.execute(select(NewsItem).where(NewsItem.summary_id == summary.id))
            for item in news_result.scalars().all():
                if hasattr(self, "mark_article_read"):
                    await self.mark_article_read(
                        session, item.original_link, summary.board_id, is_read=True, commit=False
                    )
        await session.commit()

    async def get_unviewed_dates(self, session: AsyncSession, limit: int = 7) -> list[str]:
        """Return dates that still have unread articles."""
        if hasattr(self, "get_unread_dates"):
            return await self.get_unread_dates(session, None, limit=limit)
        return []

    async def get_gap_dates(self, session: AsyncSession, days: int = 7, board_id: int | None = None) -> list[str]:
        """Return dates within the retention window that have NO DailySummary."""
        today = datetime.now()
        all_dates = [(today - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(1, days + 1)]
        # Dates that DO have a summary
        stmt = select(DailySummary.date).where(DailySummary.date.in_(all_dates)).group_by(DailySummary.date)
        if board_id is not None:
            stmt = stmt.where(DailySummary.board_id == board_id)
        result = await session.execute(stmt)
        existing_dates = set(result.scalars().all())
        return sorted([d for d in all_dates if d not in existing_dates])

    async def get_view_status_map(
        self, session: AsyncSession, limit: int = 14, board_id: int | None = None
    ) -> dict[str, str | None]:
        """Return {date: viewed_at_iso_or_None}; None means at least one unread item."""
        stmt = select(DailySummary.date).group_by(DailySummary.date).order_by(desc(DailySummary.date)).limit(limit)
        if board_id is not None:
            stmt = stmt.where(DailySummary.board_id == board_id)
        result = await session.execute(stmt)
        dates = list(result.scalars().all())
        out: dict[str, str | None] = {}
        for date in dates:
            board_match = or_(
                ArticleReadState.board_id == DailySummary.board_id,
                and_(ArticleReadState.board_id.is_(None), DailySummary.board_id.is_(None)),
            )
            unread_stmt = (
                select(func.count(NewsItem.id))
                .join(DailySummary, DailySummary.id == NewsItem.summary_id)
                .outerjoin(
                    ArticleReadState,
                    and_(
                        ArticleReadState.article_url == NewsItem.original_link,
                        board_match,
                    ),
                )
                .where(
                    DailySummary.date == date,
                    NewsItem.original_link.is_not(None),
                    NewsItem.original_link != "",
                    or_(ArticleReadState.id.is_(None), ArticleReadState.is_read.is_(False)),
                )
            )
            if board_id is not None:
                unread_stmt = unread_stmt.where(DailySummary.board_id == board_id)
            unread_count = (await session.execute(unread_stmt)).scalar_one()
            if unread_count:
                out[date] = None
                continue
            read_stmt = (
                select(func.max(ArticleReadState.read_at))
                .join(NewsItem, NewsItem.original_link == ArticleReadState.article_url)
                .join(DailySummary, DailySummary.id == NewsItem.summary_id)
                .where(DailySummary.date == date)
            )
            if board_id is not None:
                read_stmt = read_stmt.where(DailySummary.board_id == board_id)
            read_at = (await session.execute(read_stmt)).scalar_one_or_none()
            out[date] = read_at.isoformat() if read_at else None
        return out

    async def get_cache_overview(self, session: AsyncSession, limit: int = 14, board_id: int | None = None) -> dict:
        """Return all stored summaries with viewed status for cache viewer."""
        view_map = await self.get_view_status_map(session, limit=limit, board_id=board_id)
        history = await self.get_summary_history(session, limit=limit, board_id=board_id)

        items = []
        for arch in history.archive_items:
            items.append(
                {
                    "date": arch.date,
                    "overview_preview": arch.overview_preview,
                    "news_count": arch.news_count,
                    "source_stats": arch.source_stats,
                    "top_categories": arch.top_categories,
                    "viewed_at": view_map.get(arch.date),
                }
            )

        unviewed_count = sum(1 for i in items if i["viewed_at"] is None)
        return {
            "items": items,
            "total": len(items),
            "unviewed_count": unviewed_count,
        }

    async def cleanup_old_data(self, session: AsyncSession, days_to_keep: int = 7) -> int:
        threshold_date = (datetime.now() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")

        statement = select(DailySummary).where(DailySummary.date < threshold_date)
        result = await session.execute(statement)
        old_summaries = result.scalars().all()

        if not old_summaries:
            return 0

        summary_ids = [s.id for s in old_summaries]

        news_statement = select(NewsItem.original_link).where(NewsItem.summary_id.in_(summary_ids))
        news_result = await session.execute(news_statement)
        candidate_urls = {url for url in news_result.scalars().all() if url}

        urls_to_delete: list[str] = []
        if candidate_urls:
            retained_statement = select(NewsItem.original_link).where(
                NewsItem.original_link.in_(candidate_urls),
                NewsItem.summary_id.not_in(summary_ids),
            )
            retained_result = await session.execute(retained_statement)
            retained_urls = {url for url in retained_result.scalars().all() if url}
            urls_to_delete = sorted(candidate_urls - retained_urls)

        if urls_to_delete:
            from app.services.rag_service import delete_collections_by_urls

            await delete_collections_by_urls(urls_to_delete)

        if urls_to_delete:
            await session.execute(sa_delete(UserFeedback).where(UserFeedback.article_url.in_(urls_to_delete)))
            await session.execute(sa_delete(ChatMessage).where(ChatMessage.article_url.in_(urls_to_delete)))
            await session.execute(sa_delete(ArticleOverview).where(ArticleOverview.article_url.in_(urls_to_delete)))
            await session.execute(sa_delete(ArticleReadState).where(ArticleReadState.article_url.in_(urls_to_delete)))

        for s in old_summaries:
            await session.delete(s)

        await session.commit()
        logger.info("Cleanup removed %s summaries older than %s", len(old_summaries), threshold_date)
        return len(old_summaries)
