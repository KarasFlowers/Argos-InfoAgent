import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.core.db import get_session
from app.services.catchup_service import board_catchup_days
from app.services.db_service import db_service
from app.services.dedup_service import normalize_url
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/catchup/status")
async def get_catchup_status(
    board: str | None = None,
    max_days: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Lightweight check: how many unread articles and missing summaries exist."""
    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None
    board_catchup = board_catchup_days(board_obj)
    effective_days = max_days if max_days > 0 else board_catchup
    if effective_days <= 0:
        return {
            "unread_article_count": 0,
            "unread_date_count": 0,
            "first_unread_date": None,
            "unviewed_dates": [],
            "gap_dates": [],
            "unviewed_count": 0,
            "gap_count": 0,
            "earliest_unviewed": None,
            "catchup_days": board_catchup,
        }
    safe_days = max(1, min(effective_days, 30))

    today_str = datetime.now().strftime("%Y-%m-%d")
    unread_rows = await db_service.get_unread_summary_items(session, board_id, days=safe_days)
    unread_rows = [(date_value, item) for date_value, item in unread_rows if date_value != today_str]
    unread_dates = sorted({date_value for date_value, _ in unread_rows}, reverse=True)
    gaps = await db_service.get_gap_dates(session, days=safe_days, board_id=board_id)

    return {
        "unread_article_count": len(unread_rows),
        "unread_date_count": len(unread_dates),
        "first_unread_date": unread_dates[-1] if unread_dates else None,
        "unviewed_dates": unread_dates,
        "gap_dates": gaps,
        "unviewed_count": len(unread_dates),
        "gap_count": len(gaps),
        "earliest_unviewed": unread_dates[-1] if unread_dates else None,
        "catchup_days": board_catchup,
    }


@router.post("/catchup")
async def generate_catchup_digest(
    board: str | None = None,
    max_days: int = 7,
    session: AsyncSession = Depends(get_session),
):
    """Backfill gap days + generate a condensed digest of all unread content."""
    safe_days = max(1, min(max_days, 14))
    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None

    if not board_obj:
        raise HTTPException(status_code=500, detail="No board configured.")

    today_str = datetime.now().strftime("%Y-%m-%d")
    gaps = await db_service.get_gap_dates(session, days=safe_days, board_id=board_id)

    backfilled_dates: list[str] = []

    if gaps:
        earliest_gap = gaps[0]
        now = datetime.now(UTC)
        try:
            earliest_dt = datetime.strptime(earliest_gap, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            earliest_dt = now
        since_hours = max(24, int((now - earliest_dt).total_seconds() / 3600))

        try:
            from app.services.source_adapters import UnknownSourceTypeError, get_adapter

            adapter = get_adapter(board_obj.source_type)
            summary, _content_fallback = await adapter.produce(
                board=board_obj,
                session=session,
                since_hours=since_hours,
            )
            if summary:
                for gap_date in gaps:
                    summary.date = gap_date
                    try:
                        await db_service.save_summary(session, summary, board_id=board_id)
                        backfilled_dates.append(gap_date)
                    except IntegrityError:
                        await session.rollback()
                        logger.warning("Backfill summary already exists for %s", gap_date)
                    except Exception:
                        logger.exception("Failed to save backfill for %s", gap_date)
                        await session.rollback()
        except UnknownSourceTypeError as error:
            logger.error("Catchup backfill: unsupported source_type '%s': %s", board_obj.source_type, error)
        except Exception:
            logger.exception("Catchup backfill failed for board '%s'", board_obj.slug)

    unread_rows = await db_service.get_unread_summary_items(session, board_id, days=safe_days)
    unread_rows = [(date_value, item) for date_value, item in unread_rows if date_value != today_str]

    def _url_key(url: str) -> str:
        return normalize_url(url).strip().lower() if url else ""

    def _quality_score(item) -> int:
        return len(item.key_points or []) * 3 + len(item.tags or []) + len(item.headline or "")

    unread_rows.sort(key=lambda row: (row[0], _quality_score(row[1])), reverse=True)

    summaries_by_date: dict[str, dict] = {}
    seen_urls: set[str] = set()
    seen_clusters: set[int] = set()
    covered_urls: list[str] = []
    for date_value, item in unread_rows:
        url_key = _url_key(item.original_link)
        cluster_id = int(item.cluster_id) if item.cluster_id else None
        if url_key and url_key in seen_urls:
            continue
        if cluster_id and cluster_id in seen_clusters:
            continue
        if url_key:
            seen_urls.add(url_key)
        if cluster_id:
            seen_clusters.add(cluster_id)
        covered_urls.append(item.original_link)

        entry = summaries_by_date.setdefault(
            date_value,
            {
                "date": date_value,
                "overview": "",
                "perspective": "overview",
                "top_news": [],
                "source_stats": {},
                "recommendation_report": {},
            },
        )
        entry["top_news"].append(
            {
                "headline": item.headline,
                "category": item.category,
                "key_points": item.key_points or [],
                "tags": item.tags or [],
                "topic_path": item.topic_path or "",
                "original_link": item.original_link,
                "source": item.source,
                "is_read": False,
                "cluster_id": item.cluster_id,
                "is_catchup": True,
                "original_date": date_value,
            }
        )

    for date_value, entry in summaries_by_date.items():
        full = await db_service.get_summary_by_date(session, date_value, board_id=board_id)
        if full:
            entry["overview"] = full.overview
            entry["source_stats"] = full.source_stats or {}

    all_dates = sorted(summaries_by_date.keys())
    summaries_data = [summaries_by_date[date_value] for date_value in all_dates]

    if not summaries_data:
        return {
            "digest": None,
            "dates_covered": [],
            "backfilled_dates": backfilled_dates,
            "total_items": 0,
            "message": "No unread content to digest.",
        }

    digest = await llm_service.generate_catchup_digest(
        summaries_data, output_language=getattr(board_obj, "output_language", None)
    )

    if digest:
        for url in covered_urls:
            await db_service.mark_article_read(session, url, board_id, is_read=True, commit=False)
        await session.commit()

    return {
        "digest": digest.model_dump() if digest else None,
        "dates_covered": all_dates,
        "backfilled_dates": backfilled_dates,
        "total_items": len(digest.top_news) if digest else 0,
    }
