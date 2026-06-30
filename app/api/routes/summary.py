import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.core.config import settings
from app.core.db import get_session
from app.models.schemas import DailySummaryResponse
from app.services.briefing_service import build_briefing_events
from app.services.catchup_service import board_catchup_days, collect_catchup_news
from app.services.db_service import db_service
from app.services.learning_service import rerank_summary_items
from app.services.llm_service import llm_service
from app.services.recommendation_explain import enrich_summary_explanations

logger = logging.getLogger(__name__)

router = APIRouter()
_summary_generation_lock = asyncio.Lock()
_catchup_backfill_inflight: set[int] = set()


async def _collect_catchup_news(
    session: AsyncSession,
    board_id: int | None,
    catchup_days: int,
    today_str: str,
    exclude_items: list | None = None,
) -> list:
    return await collect_catchup_news(
        session,
        board_id,
        catchup_days,
        today_str,
        exclude_items=exclude_items,
        importance_selector=llm_service.select_important_catchup_indices,
    )


async def _mark_items_read(
    session: AsyncSession,
    items: list,
    board_id: int | None,
    *,
    mutate_response: bool = True,
) -> None:
    """Mark article URLs read, optionally updating response objects in place."""
    for item in items or []:
        url = getattr(item, "original_link", "") or getattr(item, "url", "")
        if not url:
            continue
        await db_service.mark_article_read(session, url, board_id, is_read=True, commit=False)
        if mutate_response and hasattr(item, "is_read"):
            item.is_read = True
    await session.commit()


async def _attach_auto_catchup(
    session: AsyncSession,
    summary,
    board_obj,
    board_id: int | None,
    search_date: str,
    *,
    trigger_backfill: bool = True,
    log_context: str = "summary",
) -> None:
    """Attach auto-catchup news for today's summary view, best-effort."""
    if not summary:
        return
    try:
        catchup_days = board_catchup_days(board_obj)
        if trigger_backfill and catchup_days > 0:
            _trigger_catchup_backfill(board_id, getattr(board_obj, "slug", ""), catchup_days)
        summary.catchup_news = await _collect_catchup_news(
            session,
            board_id,
            catchup_days,
            search_date,
            exclude_items=getattr(summary, "top_news", None) or [],
        )
        await _mark_items_read(
            session,
            summary.catchup_news,
            board_id,
            mutate_response=False,
        )
    except Exception:
        logger.debug("Auto-catchup collection skipped for %s", log_context)


async def _attach_source_analysis(
    session: AsyncSession,
    summary,
    board_id: int | None,
) -> None:
    """Attach recent coverage-difference analysis to a summary response."""
    if not summary:
        return
    try:
        from app.services.source_insights_service import get_source_coverage_analysis

        summary.source_analysis = await get_source_coverage_analysis(
            session,
            board_id=board_id,
            date=summary.date,
            days=3,
            limit=4,
        )
    except Exception:
        logger.debug("Source analysis skipped for %s", getattr(summary, "date", "unknown"))


async def _attach_event_tracks(
    session: AsyncSession,
    summary,
    board_id: int | None,
) -> None:
    """Attach recent story evolution tracks to a summary response."""
    if not summary:
        return
    top_news = getattr(summary, "top_news", None) or []
    if not top_news:
        summary.events = []
        return
    try:
        summary.events = await build_briefing_events(
            session,
            board_id,
            top_news,
            getattr(summary, "date", datetime.now().strftime("%Y-%m-%d")),
        )
    except Exception:
        summary.events = []
        logger.debug("Event track attachment skipped for %s", getattr(summary, "date", "unknown"))


async def _backfill_gap_days(board_id: int | None, board_slug: str, max_days: int) -> None:
    """Background job: scrape and summarise gap days for auto-catchup."""

    from app.core.db import AsyncSessionLocal
    from app.core.scheduler import track_task_run
    from app.services.source_adapters import UnknownSourceTypeError, get_adapter

    key = board_id if board_id is not None else -1
    if key in _catchup_backfill_inflight:
        return
    _catchup_backfill_inflight.add(key)
    try:
        async with track_task_run("catchup_backfill", trigger_type="auto", board_id=board_id) as tr:
            async with AsyncSessionLocal() as session:
                board_obj = (
                    await db_service.get_board_by_id(session, board_id)
                    if board_id
                    else await db_service.get_default_board(session)
                )
                if not board_obj:
                    return
                safe_days = max(1, min(max_days, 14))
                gaps = await db_service.get_gap_dates(session, days=safe_days, board_id=board_id)
                if not gaps:
                    return
                tr.progress_label = f"backfilling {len(gaps)} gap day(s)"

                earliest_gap = gaps[0]
                now = datetime.now(UTC)
                try:
                    earliest_dt = datetime.strptime(earliest_gap, "%Y-%m-%d").replace(tzinfo=UTC)
                except ValueError:
                    earliest_dt = now
                since_hours = max(24, int((now - earliest_dt).total_seconds() / 3600))

                try:
                    adapter = get_adapter(board_obj.source_type)
                    summary, _ = await adapter.produce(
                        board=board_obj,
                        session=session,
                        since_hours=since_hours,
                    )
                except UnknownSourceTypeError as error:
                    logger.error("Catchup backfill: unsupported source_type '%s': %s", board_obj.source_type, error)
                    return
                if not summary:
                    return

                for gap_date in gaps:
                    summary.date = gap_date
                    try:
                        await db_service.save_summary(session, summary, board_id=board_id)
                    except IntegrityError:
                        await session.rollback()
                    except Exception:
                        logger.exception("Failed to save backfill for %s", gap_date)
                        await session.rollback()
                logger.info("Auto-catchup backfilled %s gap day(s) for board '%s'", len(gaps), board_slug)
    except Exception:
        logger.exception("Auto-catchup backfill failed for board '%s'", board_slug)
    finally:
        _catchup_backfill_inflight.discard(key)


def _trigger_catchup_backfill(board_id: int | None, board_slug: str, max_days: int) -> None:
    """Fire-and-forget: schedule gap-day backfill without blocking the request."""
    try:
        from app.core.background import register_background_task

        register_background_task(asyncio.create_task(_backfill_gap_days(board_id, board_slug, max_days)))
    except RuntimeError:
        logger.debug("No running loop for catchup backfill; skipped")


@router.get("/summary", response_model=DailySummaryResponse)
async def generate_summary(
    force: bool = False,
    date: str | None = None,
    preference: str | None = None,
    save_preference: bool = False,
    board: str | None = None,
    perspective: str = "overview",
    session: AsyncSession = Depends(get_session),
):
    """
    Returns AI summary for today or a specific date, scoped to a board.
    If board is not provided, falls back to the default board (tech).
    If date is provided, only fetch from DB (no external generation for history).
    """
    search_date = date if date else datetime.now().strftime("%Y-%m-%d")
    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None

    if not force:
        existing_summary = await db_service.get_summary_by_date(
            session, search_date, board_id=board_id, perspective=perspective
        )
        if existing_summary:
            try:
                existing_summary.top_news = await rerank_summary_items(
                    existing_summary.top_news,
                    session=session,
                    board_id=board_id,
                )
            except Exception:
                logger.debug("Persona reranking skipped (no feedback data or model not loaded)")
            try:
                await _mark_items_read(session, existing_summary.top_news, board_id)
            except Exception:
                logger.debug("Article read tracking skipped for %s", search_date)
            if not date:
                await _attach_auto_catchup(
                    session,
                    existing_summary,
                    board_obj,
                    board_id,
                    search_date,
                    log_context="cached summary",
                )
            await _attach_event_tracks(session, existing_summary, board_id)
            await _attach_source_analysis(session, existing_summary, board_id)
            await enrich_summary_explanations(existing_summary, session, board_id)
            return existing_summary

    if date and date != datetime.now().strftime("%Y-%m-%d"):
        raise HTTPException(status_code=404, detail=f"No historical summary found for {date}.")

    async with _summary_generation_lock:
        if not force:
            existing_summary = await db_service.get_summary_by_date(
                session, search_date, board_id=board_id, perspective=perspective
            )
            if existing_summary:
                try:
                    existing_summary.top_news = await rerank_summary_items(
                        existing_summary.top_news,
                        session=session,
                        board_id=board_id,
                    )
                except Exception:
                    logger.debug("Persona reranking skipped for cached summary")
                try:
                    await _mark_items_read(session, existing_summary.top_news, board_id)
                except Exception:
                    logger.debug("Article read tracking skipped for %s", search_date)
                if not date:
                    await _attach_auto_catchup(
                        session,
                        existing_summary,
                        board_obj,
                        board_id,
                        search_date,
                        trigger_backfill=False,
                        log_context="cached summary after lock",
                    )
                await _attach_event_tracks(session, existing_summary, board_id)
                await _attach_source_analysis(session, existing_summary, board_id)
                await enrich_summary_explanations(existing_summary, session, board_id)
                return existing_summary

        from app.services.source_adapters import UnknownSourceTypeError, get_adapter

        if board_obj is None:
            raise HTTPException(status_code=500, detail="No board configured — cannot generate summary.")

        if not settings.effective_llm_api_key:
            raise HTTPException(
                status_code=503,
                detail="LLM API key 未配置。请在 .env 中设置 LLM_API_KEY 或 DEEPSEEK_API_KEY 后重启服务。",
            )

        try:
            adapter = get_adapter(board_obj.source_type)
        except UnknownSourceTypeError as error:
            logger.error("Board '%s' has unsupported source_type: %s", board_obj.slug, error)
            raise HTTPException(status_code=500, detail=str(error)) from error

        summary, content_fallback = await adapter.produce(
            board=board_obj,
            session=session,
            one_time_preference=preference,
        )

        if not summary:
            raise HTTPException(status_code=500, detail="Failed to generate AI summary.")

        active_perspectives = None
        if board_obj and board_obj.perspectives and isinstance(board_obj.perspectives, dict):
            active_perspectives = board_obj.perspectives.get("active")

        if active_perspectives and len(active_perspectives) > 1:
            perspective_results = await llm_service.generate_perspective_summaries(
                content_items=[],
                session=session,
                board=board_obj,
                perspectives=active_perspectives,
                seed_summary=summary,
            )

            for persp_summary, _persp_fallback in perspective_results:
                if persp_summary:
                    try:
                        if force:
                            await db_service.replace_summary(session, persp_summary, board_id=board_id)
                        else:
                            await db_service.save_summary(session, persp_summary, board_id=board_id)
                    except IntegrityError:
                        logger.warning(
                            "Perspective summary for %s/%s already exists.", search_date, persp_summary.perspective
                        )
                        await session.rollback()
                    except Exception:
                        logger.exception("Failed to persist perspective %s", persp_summary.perspective)
                        await session.rollback()

            requested = None
            for persp_summary, _ in perspective_results:
                if persp_summary and persp_summary.perspective == perspective:
                    requested = persp_summary
                    break
            if not requested:
                requested = perspective_results[0][0] if perspective_results else summary
            summary = requested
        else:
            try:
                if force:
                    await db_service.replace_summary(session, summary, board_id=board_id)
                else:
                    await db_service.save_summary(session, summary, board_id=board_id)
            except IntegrityError:
                logger.warning("Summary for %s already exists, returning stored version.", search_date)
                await session.rollback()
                existing_summary = await db_service.get_summary_by_date(
                    session, search_date, board_id=board_id, perspective=perspective
                )
                if existing_summary:
                    try:
                        await _mark_items_read(session, existing_summary.top_news, board_id)
                    except Exception:
                        logger.debug("Article read tracking skipped for %s", search_date)
                    if not date:
                        await _attach_auto_catchup(
                            session,
                            existing_summary,
                            board_obj,
                            board_id,
                            search_date,
                            trigger_backfill=False,
                            log_context="integrity fallback summary",
                        )
                    await _attach_event_tracks(session, existing_summary, board_id)
                    await _attach_source_analysis(session, existing_summary, board_id)
                    await enrich_summary_explanations(existing_summary, session, board_id)
                    return existing_summary
                raise HTTPException(status_code=500, detail="Failed to save AI summary.") from None
            except Exception as exc:
                logger.exception("Failed to persist summary for %s", search_date)
                await session.rollback()
                raise HTTPException(status_code=500, detail="Failed to save AI summary.") from exc

        if preference and save_preference:
            try:
                await db_service.save_persona(session, content=preference, category="instruction", board_id=board_id)
            except Exception as exc:
                logger.exception("Failed to save persona preference")
                raise HTTPException(
                    status_code=500,
                    detail="Summary was generated but the preference could not be saved.",
                ) from exc

        if settings.RAG_ENABLED and settings.RAG_BACKGROUND_INGEST_ENABLED:
            from app.services.rag_service import enqueue_for_ingest

            article_urls = [item.original_link for item in summary.top_news if item.original_link]
            fallback = {u: content_fallback[u] for u in article_urls if u in content_fallback}
            enqueue_for_ingest(article_urls, fallback_contents=fallback if fallback else None)

        stored_summary = await db_service.get_summary_by_date(
            session, search_date, board_id=board_id, perspective=perspective
        )
        final = stored_summary or summary
        try:
            final.top_news = await rerank_summary_items(
                final.top_news,
                session=session,
                board_id=board_id,
            )
        except Exception:
            logger.debug("Persona reranking skipped for fresh summary")
        try:
            await _mark_items_read(session, final.top_news, board_id)
        except Exception:
            logger.debug("Article read tracking skipped for %s", search_date)
        if not date:
            await _attach_auto_catchup(
                session,
                final,
                board_obj,
                board_id,
                search_date,
                log_context="fresh summary",
            )
        await _attach_event_tracks(session, final, board_id)
        await _attach_source_analysis(session, final, board_id)
        await enrich_summary_explanations(final, session, board_id)
        return final
