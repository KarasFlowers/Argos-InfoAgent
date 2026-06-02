import asyncio
import html as html_mod
import logging
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models.schemas import DailySummaryResponse, RSSResponse, SummaryHistoryResponse
from app.services.db_service import db_service
from app.services.learning_service import get_inferred_interests, rerank_summary_items
from app.services.llm_service import llm_service
from app.services.metrics_service import metrics_service
from app.services.rss_service import fetch_all_feeds
from app.services.email_service import email_service

logger = logging.getLogger(__name__)

class PersonaCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="instruction", max_length=64)
    board_id: Optional[int] = None  # null = global persona


class BoardCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=128)
    icon: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=500)
    system_prompt: str = Field(default="", max_length=4000)
    source_type: str = Field(default="rss", max_length=32)
    source_config: dict = Field(default_factory=dict)
    display_order: int = Field(default=0)
    schedule: str = Field(default="")
    notify_channels: str = Field(default="")
    perspectives: Optional[dict] = None
    prompt_key: str = Field(default="daily_briefing")
    output_language: str = Field(default="auto", pattern=r"^(auto|zh|en)$")


class BoardUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    icon: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = Field(default=None, max_length=500)
    system_prompt: Optional[str] = Field(default=None, max_length=4000)
    source_type: Optional[str] = Field(default=None, max_length=32)
    source_config: Optional[dict] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None
    schedule: Optional[str] = None
    notify_channels: Optional[str] = None
    perspectives: Optional[dict] = None
    prompt_key: Optional[str] = None
    output_language: Optional[str] = Field(default=None, pattern=r"^(auto|zh|en)$")


class BoardPreviewRequest(BaseModel):
    slug: str = Field(default="preview-board", min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    name: str = Field(default="预览板块", min_length=1, max_length=128)
    icon: str = Field(default="📌", max_length=32)
    description: str = Field(default="", max_length=500)
    system_prompt: str = Field(default="", max_length=4000)
    source_type: str = Field(default="rss", max_length=32)
    source_config: dict = Field(default_factory=dict)
    schedule: str = Field(default="")
    notify_channels: str = Field(default="")
    perspectives: Optional[dict] = None
    prompt_key: str = Field(default="daily_briefing")
    original_slug: Optional[str] = Field(default=None, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    perspective: str = Field(default="overview", max_length=64)
    output_language: str = Field(default="auto", pattern=r"^(auto|zh|en)$")


class BoardWizardMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class BoardWizardRequest(BaseModel):
    messages: list[BoardWizardMessage] = Field(min_length=1, max_length=20)


_summary_generation_lock = asyncio.Lock()

api_router = APIRouter()

@api_router.get("/feed")
async def get_rss_feed(session: AsyncSession = Depends(get_session)):
    """
    Export the last 7 daily summaries as a standard RSS 2.0 XML feed.
    """
    history = await db_service.get_summary_history(session, limit=7)
    
    # We'll use the domain of the first incoming request or just a generic placeholder 
    # since we don't have a configured base URL for the app itself in settings.
    site_url = "https://argos.local"
    
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        '  <channel>',
        '    <title>Argos Daily Briefing</title>',
        f'    <link>{site_url}</link>',
        '    <description>Your personalized daily technology and AI briefing.</description>',
        '    <language>zh-cn</language>'
    ]
    
    from datetime import timezone
    for history_item in history:
        summary = await db_service.get_summary_by_date(session, history_item.date)
        if not summary:
            continue
            
        # Convert date string to proper RFC-822 date format for RSS
        try:
            dt = datetime.strptime(summary.date, "%Y-%m-%d")
            dt = dt.replace(tzinfo=timezone.utc)
            pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
        except ValueError:
            pub_date = ""

        # Build the HTML content for the RSS description
        html_content = email_service._render_html(summary)
        
        # Escape XML entities
        escaped_html = html_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")
        
        xml.append('    <item>')
        xml.append(f'      <title>{html_mod.escape(f"Argos 日报 - {summary.date}")}</title>')
        xml.append(f'      <link>{html_mod.escape(f"{site_url}/?date={summary.date}")}</link>')
        xml.append(f'      <guid isPermaLink="false">argos-{html_mod.escape(summary.date)}</guid>')
        if pub_date:
            xml.append(f'      <pubDate>{pub_date}</pubDate>')
        xml.append(f'      <description>{escaped_html}</description>')
        xml.append('    </item>')
        
    xml.append('  </channel>')
    xml.append('</rss>')
    
    return Response(content="\n".join(xml), media_type="application/rss+xml")


@api_router.get("/metrics")
async def get_system_metrics(date: str | None = None):
    """
    Get system metrics (token usage and latency) for a specific date (defaults to today).
    """
    return await metrics_service.get_daily_metrics(date)


@api_router.get("/metrics/cost")
async def get_cost_breakdown(date: str | None = None):
    """
    Get per-label LLM cost breakdown (token usage per label) for a given date.
    """
    return await metrics_service.get_cost_breakdown(date)


@api_router.get("/insights/heatmap")
async def get_insights_heatmap(
    session: AsyncSession = Depends(get_session),
    days: int = Query(default=7, ge=1, le=30),
):
    """
    Get a topic heatmap (category + tag counts per day) for the last N days.
    """
    from app.services.insights_service import get_topic_heatmap
    return await get_topic_heatmap(session, days)


@api_router.get("/insights/timeline")
async def get_insights_timeline(
    session: AsyncSession = Depends(get_session),
    entity: str = Query(..., min_length=1),
    days: int = Query(default=30, ge=1, le=90),
):
    """
    Get a timeline of news items mentioning a specific entity keyword.
    """
    from app.services.insights_service import get_entity_timeline
    return await get_entity_timeline(session, entity, days)


@api_router.get("/insights/topic_tree")
async def get_insights_topic_tree(
    session: AsyncSession = Depends(get_session),
    days: int = Query(default=7, ge=1, le=30),
):
    """Get a hierarchical topic tree built from topic_path fields."""
    from app.services.insights_service import get_topic_tree
    return await get_topic_tree(session, days)


@api_router.get("/insights/trending")
async def get_insights_trending(
    session: AsyncSession = Depends(get_session),
    days: int = Query(default=7, ge=2, le=30),
    top_n: int = Query(default=10, ge=1, le=50),
):
    """Find topics trending upward in the recent half vs prior half of the period."""
    from app.services.insights_service import get_trending_topics
    return await get_trending_topics(session, days, top_n)


@api_router.post("/research")
async def deep_research(payload: dict):
    """
    Run a simplified deep research cycle on a question.

    Body: {"question": "...", "max_sub_queries": 4, "rag_top_k": 5}
    """
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="'question' is required.")
    from app.services.research_service import research
    result = await research(
        question=question,
        max_sub_queries=int(payload.get("max_sub_queries", 4)),
        rag_top_k=int(payload.get("rag_top_k", 5)),
    )
    return result


@api_router.get("/ping")
async def ping():
    """
    Health check endpoint.
    """
    return {"status": "ok", "message": "pong"}


@api_router.get("/admin/tasks")
async def list_task_runs(
    kind: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List recent background task runs for observability."""
    from sqlalchemy import select, desc
    from app.models.domain import TaskRun

    stmt = select(TaskRun).order_by(desc(TaskRun.id))
    if kind:
        stmt = stmt.where(TaskRun.kind == kind)
    if status:
        stmt = stmt.where(TaskRun.status == status)
    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    tasks = result.scalars().all()

    return [
        {
            "id": t.id,
            "kind": t.kind,
            "trigger_type": t.trigger_type,
            "status": t.status,
            "progress_label": t.progress_label,
            "progress_current": t.progress_current,
            "progress_total": t.progress_total,
            "stage_timings": t.stage_timings,
            "ai_call_breakdown": t.ai_call_breakdown,
            "error_summary": t.error_summary,
            "board_id": t.board_id,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tasks
    ]


@api_router.get("/admin/sources/health")
async def list_source_health(session: AsyncSession = Depends(get_session)):
    """List all sources with their current health status."""
    from app.services.source_health_service import get_all_source_health
    return await get_all_source_health(session)


@api_router.get("/admin/sources/{source_id}/health_log")
async def get_source_health_log_endpoint(
    source_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Get recent health check log for a specific source."""
    from app.services.source_health_service import get_source_health_log
    return await get_source_health_log(session, source_id, limit=limit)


@api_router.get("/feeds", response_model=list[RSSResponse])
async def manually_trigger_rss_fetch():
    """
    Manually fetch updates from all configured RSS feeds.
    """
    return await fetch_all_feeds(settings.RSS_FEEDS)


class TestFeedRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)


@api_router.post("/sources/test")
async def test_source_feed(payload: TestFeedRequest):
    """
    Test a single RSS feed URL. Returns status, article count, and sample titles.
    Does NOT cache the result.
    """
    import httpx
    import feedparser

    url = payload.url.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await client.get(url, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        entries = feed.entries or []
        feed_title = feed.feed.get("title", "Unknown Feed")

        return {
            "ok": True,
            "feed_title": feed_title,
            "article_count": len(entries),
            "sample_titles": [e.get("title", "Untitled") for e in entries[:5]],
        }
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"HTTP {e.response.status_code}"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "请求超时 (15s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


async def _resolve_board(session: AsyncSession, slug: str | None):
    """
    Resolve an optional board slug to a Board row. When slug is None,
    returns the default board. Raises 404 if slug is provided but not found.
    """
    if slug:
        board = await db_service.get_board_by_slug(session, slug)
        if not board or not board.is_active:
            raise HTTPException(status_code=404, detail=f"Board '{slug}' not found or inactive.")
        return board
    return await db_service.get_default_board(session)


@api_router.get("/summary", response_model=DailySummaryResponse)
async def generate_summary(
    force: bool = False,
    date: Optional[str] = None,
    preference: Optional[str] = None,
    save_preference: bool = False,
    board: Optional[str] = None,
    perspective: str = "overview",
    session: AsyncSession = Depends(get_session),
):
    """
    Returns AI summary for today or a specific date, scoped to a board.
    If board is not provided, falls back to the default board (tech).
    If date is provided, only fetch from DB (no external generation for history).
    """
    search_date = date if date else datetime.now().strftime("%Y-%m-%d")
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None

    # 1. Check database first (FAST PATH)
    if not force:
        existing_summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id, perspective=perspective)
        if existing_summary:
            try:
                existing_summary.top_news = await rerank_summary_items(existing_summary.top_news, session=session)
            except Exception:
                logger.debug("Persona reranking skipped (no feedback data or model not loaded)")
            # Mark date as viewed (catch-up tracking)
            try:
                await db_service.mark_date_viewed(session, search_date)
            except Exception:
                logger.debug("Viewed tracking skipped for %s", search_date)
            return existing_summary

    # If it's a historical date and not in DB, we don't generate (to save costs/avoid confusion)
    if date and date != datetime.now().strftime("%Y-%m-%d"):
        raise HTTPException(status_code=404, detail=f"No historical summary found for {date}.")

    async with _summary_generation_lock:
        if not force:
            existing_summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id, perspective=perspective)
            if existing_summary:
                try:
                    existing_summary.top_news = await rerank_summary_items(existing_summary.top_news, session=session)
                except Exception:
                    pass
                return existing_summary

        # Dispatch to the correct source adapter based on the board's source_type.
        from app.services.source_adapters import get_adapter, UnknownSourceTypeError
        if board_obj is None:
            raise HTTPException(status_code=500, detail="No board configured — cannot generate summary.")
        try:
            adapter = get_adapter(board_obj.source_type)
        except UnknownSourceTypeError as error:
            logger.error("Board '%s' has unsupported source_type: %s", board_obj.slug, error)
            raise HTTPException(status_code=500, detail=str(error))

        summary, content_fallback = await adapter.produce(
            board=board_obj,
            session=session,
            one_time_preference=preference,
        )

        if not summary:
            raise HTTPException(status_code=500, detail="Failed to generate AI summary.")

        # Check if board has multiple perspectives configured
        active_perspectives = None
        if board_obj and board_obj.perspectives and isinstance(board_obj.perspectives, dict):
            active_perspectives = board_obj.perspectives.get("active")

        if active_perspectives and len(active_perspectives) > 1:
            # Multi-perspective generation
            from app.services.llm_service import llm_service

            perspective_results = await llm_service.generate_perspective_summaries(
                content_items=[],
                session=session,
                board=board_obj,
                perspectives=active_perspectives,
                seed_summary=summary,
            )

            # Persist all perspective summaries
            for persp_summary, persp_fallback in perspective_results:
                if persp_summary:
                    try:
                        if force:
                            await db_service.replace_summary(session, persp_summary, board_id=board_id)
                        else:
                            await db_service.save_summary(session, persp_summary, board_id=board_id)
                    except IntegrityError:
                        logger.warning("Perspective summary for %s/%s already exists.", search_date, persp_summary.perspective)
                        await session.rollback()
                    except Exception:
                        logger.exception("Failed to persist perspective %s", persp_summary.perspective)
                        await session.rollback()

            # Return the requested perspective (or the first one)
            requested = None
            for persp_summary, _ in perspective_results:
                if persp_summary and persp_summary.perspective == perspective:
                    requested = persp_summary
                    break
            if not requested:
                requested = perspective_results[0][0] if perspective_results else summary
            summary = requested
        else:
            # Single perspective (standard path)
            try:
                if force:
                    await db_service.replace_summary(session, summary, board_id=board_id)
                else:
                    await db_service.save_summary(session, summary, board_id=board_id)
            except IntegrityError:
                logger.warning("Summary for %s already exists, returning stored version.", search_date)
                await session.rollback()
                existing_summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id, perspective=perspective)
                if existing_summary:
                    return existing_summary
                raise HTTPException(status_code=500, detail="Failed to save AI summary.")
            except Exception:
                logger.exception("Failed to persist summary for %s", search_date)
                await session.rollback()
                raise HTTPException(status_code=500, detail="Failed to save AI summary.")

        if preference and save_preference:
            try:
                await db_service.save_persona(
                    session, content=preference, category="instruction", board_id=board_id
                )
            except Exception:
                logger.exception("Failed to save persona preference")
                raise HTTPException(status_code=500, detail="Summary was generated but the preference could not be saved.")

        # NOTE: cleanup_old_data is now handled by APScheduler (see scheduler.py).
        # This eliminates the risk of a failed cleanup tainting the request session.

        # Enqueue articles for background RAG ingestion
        if settings.RAG_ENABLED and settings.RAG_BACKGROUND_INGEST_ENABLED:
            from app.services.rag_service import enqueue_for_ingest
            article_urls = [item.original_link for item in summary.top_news if item.original_link]
            fallback = {u: content_fallback[u] for u in article_urls if u in content_fallback}
            enqueue_for_ingest(article_urls, fallback_contents=fallback if fallback else None)

        stored_summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id, perspective=perspective)
        final = stored_summary or summary
        try:
            final.top_news = await rerank_summary_items(final.top_news, session=session)
        except Exception:
            logger.debug("Persona reranking skipped for fresh summary")
        # Mark date as viewed (catch-up tracking)
        try:
            await db_service.mark_date_viewed(session, search_date)
        except Exception:
            logger.debug("Viewed tracking skipped for %s", search_date)
        return final


@api_router.get("/briefing")
async def get_daily_briefing(
    date: Optional[str] = None,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """Structured daily briefing — richer than /summary.

    Returns grouped news with cluster info, source stats, and pipeline metadata.
    If no summary exists for the date, returns 404.
    """
    search_date = date or datetime.now().strftime("%Y-%m-%d")
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None

    existing = await db_service.get_summary_by_date(session, search_date, board_id=board_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"No briefing found for {search_date}.")

    # Group items by category for sectioned output
    sections: dict[str, list] = {}
    for item in existing.top_news:
        cat = item.category or "general"
        sections.setdefault(cat, []).append({
            "headline": item.headline,
            "key_points": item.key_points,
            "tags": item.tags,
            "topic_path": getattr(item, "topic_path", ""),
            "original_link": item.original_link,
            "source": item.source,
        })

    # Fetch clusters for this board
    clusters = []
    try:
        from app.services.clustering_service import get_clusters_for_board
        cluster_rows = await get_clusters_for_board(session, board_id=board_id, limit=10)
        clusters = [
            {"title": c.title, "item_count": c.item_count, "summary": c.summary}
            for c in cluster_rows
        ]
    except Exception:
        pass  # clustering not yet populated — graceful skip

    return {
        "date": existing.date,
        "board": board_obj.slug if board_obj else "default",
        "overview": existing.overview,
        "perspective": existing.perspective,
        "sections": sections,
        "clusters": clusters,
        "source_stats": existing.stats_json or {},
        "recommendation_report": {},
        "total_items": len(existing.top_news),
        "section_count": len(sections),
    }


class RefineRequest(BaseModel):
    date: Optional[str] = None
    board: Optional[str] = None
    instruction: str = Field(min_length=1, max_length=2000)


@api_router.post("/briefing/refine")
async def refine_daily_briefing(
    payload: RefineRequest,
    session: AsyncSession = Depends(get_session),
):
    """Refine an existing daily briefing with a user instruction.

    Creates a DailyReportRefinementSession, re-runs LLM with the instruction
    injected into persona context, and stores the refined output.
    """
    from datetime import UTC
    from app.models.domain import DailyReportRefinementSession

    search_date = payload.date or datetime.now().strftime("%Y-%m-%d")
    board_obj = await _resolve_board(session, payload.board)
    board_id = board_obj.id if board_obj else None

    # 1. Load existing summary
    existing = await db_service.get_summary_by_date(session, search_date, board_id=board_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"No summary found for {search_date} to refine.")

    # 2. Create refinement session
    rs = DailyReportRefinementSession(
        board_id=board_id,
        date=search_date,
        instruction=payload.instruction,
        original_summary_json=existing.model_dump(mode="json"),
        status="processing",
    )
    session.add(rs)
    await session.commit()
    await session.refresh(rs)
    session_id = rs.id

    # 3. Re-generate with instruction injected
    try:
        # Rebuild ContentItems from existing top_news so the pipeline has content to work with
        from app.models.schemas import ContentItem as CI
        rebuilt_items = [
            CI(
                id=f"rss:refine:{n.id}",
                source_type="rss",
                title=n.headline,
                url=n.original_link,
                source=n.source,
            )
            for n in existing.top_news
        ]

        refined, _ = await llm_service.generate_daily_summary_from_items(
            content_items=rebuilt_items,
            session=session,
            board=board_obj,
            one_time_preference=payload.instruction,
        )

        if refined:
            rs.refined_summary_json = refined.model_dump(mode="json")
            rs.status = "done"
        else:
            rs.status = "failed"
            rs.error_message = "LLM returned no output"
    except Exception as exc:
        rs.status = "failed"
        rs.error_message = str(exc)[:500]

    rs.finished_at = datetime.now(UTC)
    await session.commit()

    return {
        "session_id": session_id,
        "status": rs.status,
        "refined_summary": rs.refined_summary_json,
        "error": rs.error_message or None,
    }


@api_router.get("/briefing/refine/{session_id}")
async def get_refinement_session(
    session_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Retrieve a refinement session result."""
    from sqlalchemy import select
    from app.models.domain import DailyReportRefinementSession

    stmt = select(DailyReportRefinementSession).where(DailyReportRefinementSession.id == session_id)
    result = await session.execute(stmt)
    rs = result.scalar_one_or_none()
    if not rs:
        raise HTTPException(status_code=404, detail="Refinement session not found.")

    return {
        "session_id": rs.id,
        "board_id": rs.board_id,
        "date": rs.date,
        "instruction": rs.instruction,
        "status": rs.status,
        "refined_summary": rs.refined_summary_json,
        "error": rs.error_message or None,
        "created_at": rs.created_at.isoformat() if rs.created_at else None,
        "finished_at": rs.finished_at.isoformat() if rs.finished_at else None,
    }


@api_router.get("/persona")
async def get_persona(
    board: Optional[str] = None,
    include_global: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """
    Get active persona instructions. When board is provided, returns that
    board's personas (plus global ones if include_global=True).
    """
    board_id: int | None = None
    if board is not None:
        board_obj = await _resolve_board(session, board)
        board_id = board_obj.id if board_obj else None
    return await db_service.get_active_personas(
        session, board_id=board_id, include_global=include_global
    )


@api_router.post("/persona")
async def add_persona(
    payload: PersonaCreateRequest,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Add a new persona instruction.
    Priority: payload.board_id > ?board=slug > global (null).
    """
    target_board_id: int | None = payload.board_id
    if target_board_id is None and board:
        board_obj = await _resolve_board(session, board)
        target_board_id = board_obj.id if board_obj else None
    await db_service.save_persona(
        session, payload.content, payload.category, board_id=target_board_id
    )
    return {"status": "ok"}


@api_router.delete("/persona/{persona_id}")
async def delete_persona(persona_id: int, session: AsyncSession = Depends(get_session)):
    """
    Delete a persona instruction.
    """
    await db_service.delete_persona(session, persona_id)
    return {"status": "ok"}


class InterestOptionsRequest(BaseModel):
    headline: str = Field(min_length=1, max_length=500)
    key_points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


@api_router.post("/feedback/interest-options")
async def feedback_interest_options(payload: InterestOptionsRequest):
    """
    Given a just-liked article, return 3-4 LLM-suggested abstract interest
    descriptions (e.g. "新 AI 模型发布动态") for the user to choose from,
    so we can capture *real* intent rather than the literal article topic.
    """
    options = await llm_service.extract_interest_options(
        headline=payload.headline,
        key_points=payload.key_points,
        tags=payload.tags,
    )
    return {"options": options}


class SaveInterestReasonRequest(BaseModel):
    content: str = Field(min_length=1, max_length=200)


@api_router.post("/feedback/save-reason")
async def feedback_save_reason(
    payload: SaveInterestReasonRequest,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Persist the user's chosen abstract interest reason as an `extracted`
    persona, scoped to the current board when provided.
    """
    board_id: int | None = None
    if board:
        board_obj = await _resolve_board(session, board)
        board_id = board_obj.id if board_obj else None
    await db_service.save_persona(
        session, content=payload.content, category="extracted", board_id=board_id
    )
    return {"status": "ok"}


# ------------------------------------------------------------------
# Saved articles (Favorites / Read Later)
# ------------------------------------------------------------------


class SavedArticleRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)
    status: Literal["favorite", "read_later"]
    headline: str = Field(default="", max_length=500)
    source: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=120)
    board: str = Field(default="", max_length=64)


class SavedArticleDeleteRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)
    status: Literal["favorite", "read_later"]


@api_router.get("/saved")
async def list_saved_articles(
    status: Literal["favorite", "read_later"] = Query("favorite"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """List saved articles for a given status (favorite | read_later)."""
    from app.services.saved_service import list_saved
    return {"status": status, "items": await list_saved(status, limit=limit)}


@api_router.get("/saved/urls")
async def get_saved_url_map_endpoint():
    """Return {url: [status, ...]} for highlighting saved articles in the UI."""
    from app.services.saved_service import get_saved_url_map
    return await get_saved_url_map()


@api_router.post("/saved")
async def add_saved_article(payload: SavedArticleRequest):
    """Save an article under the given status."""
    from app.services.saved_service import add_saved
    try:
        await add_saved(
            payload.url,
            payload.status,
            headline=payload.headline,
            source=payload.source,
            category=payload.category,
            board_slug=payload.board,
        )
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@api_router.delete("/saved")
async def remove_saved_article(payload: SavedArticleDeleteRequest):
    """Remove a saved article for the given status."""
    from app.services.saved_service import remove_saved
    try:
        await remove_saved(payload.url, payload.status)
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@api_router.get("/persona/inferred")
async def get_inferred_persona(session: AsyncSession = Depends(get_session)):
    """
    Analyze feedback history to infer user interests.
    """
    return await get_inferred_interests(session)


@api_router.get("/preferences")
async def get_explicit_preferences(
    board: Optional[str] = None,
    include_global: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """
    Get all explicit preference tags grouped by category, optionally scoped to a board.
    """
    board_id: int | None = None
    if board is not None:
        board_obj = await _resolve_board(session, board)
        board_id = board_obj.id if board_obj else None

    return await db_service.get_explicit_preferences_detailed(
        session, board_id=board_id, include_global=include_global
    )


# ------------------------------------------------------------------
# Board (custom section) CRUD
# ------------------------------------------------------------------

def _serialize_board(board) -> dict:
    return {
        "id": board.id,
        "slug": board.slug,
        "name": board.name,
        "icon": board.icon,
        "description": board.description,
        "system_prompt": board.system_prompt,
        "source_type": board.source_type,
        "source_config": board.source_config or {},
        "perspectives": board.perspectives or {},
        "prompt_key": board.prompt_key or "daily_briefing",
        "output_language": getattr(board, "output_language", "auto") or "auto",
        "schedule": board.schedule or "",
        "notify_channels": board.notify_channels or "",
        "display_order": board.display_order,
        "is_active": board.is_active,
        "is_default": board.is_default,
    }


def _validate_board_source_payload(source_type: str, source_config: dict | None) -> None:
    from app.services.source_adapters import VALID_SOURCE_TYPES
    if source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"source_type must be one of {VALID_SOURCE_TYPES}.")

    from app.models.source_configs import SOURCE_CONFIG_MODELS
    config_model = SOURCE_CONFIG_MODELS.get(source_type)
    if config_model and source_config:
        try:
            config_model.model_validate(source_config)
        except Exception as val_err:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid source_config for type '{source_type}': {val_err}",
            )


async def _run_board_preview_runtime(
    board,
    session: AsyncSession,
    perspective: str = "overview",
):
    from app.services.source_adapters import get_adapter, UnknownSourceTypeError

    if not board.is_active:
        raise HTTPException(status_code=400, detail="Cannot preview an inactive board.")

    try:
        adapter = get_adapter(board.source_type)
    except UnknownSourceTypeError as error:
        raise HTTPException(status_code=400, detail=str(error))

    try:
        summary_resp, _ = await adapter.produce(board, session)
        if not summary_resp:
            raise HTTPException(status_code=500, detail="Adapter returned no content for preview.")

        active_perspectives = None
        if board.perspectives and isinstance(board.perspectives, dict):
            active_perspectives = board.perspectives.get("active")

        if active_perspectives and len(active_perspectives) > 1:
            perspective_results = await llm_service.generate_perspective_summaries(
                content_items=[],
                session=session,
                board=board,
                perspectives=active_perspectives,
                seed_summary=summary_resp,
            )
            requested = None
            for persp_summary, _ in perspective_results:
                if persp_summary and persp_summary.perspective == perspective:
                    requested = persp_summary
                    break
            if not requested:
                requested = next((item for item, _ in perspective_results if item), summary_resp)
            summary_resp = requested

        return summary_resp
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(error)}")


@api_router.get("/boards")
async def list_boards(
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """List all boards, ordered by display_order."""
    boards = await db_service.list_boards(session, active_only=not include_inactive)
    return [_serialize_board(b) for b in boards]


@api_router.post("/boards")
async def create_board(
    payload: BoardCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new custom board."""
    existing = await db_service.get_board_by_slug(session, payload.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Board '{payload.slug}' already exists.")
    _validate_board_source_payload(payload.source_type, payload.source_config)
    board = await db_service.create_board(
        session,
        slug=payload.slug,
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        system_prompt=payload.system_prompt,
        source_type=payload.source_type,
        source_config=payload.source_config,
        display_order=payload.display_order,
        schedule=payload.schedule,
        notify_channels=payload.notify_channels,
        perspectives=payload.perspectives,
        prompt_key=payload.prompt_key,
        output_language=payload.output_language,
    )
    return _serialize_board(board)


@api_router.post("/boards/wizard")
async def board_wizard(payload: BoardWizardRequest):
    """
    Interactive AI-guided wizard to help users configure a new board.
    Accepts a conversation history, returns a reply plus (when ready) a suggested config.
    """
    result = await llm_service.wizard_suggest_board(
        [m.model_dump() for m in payload.messages]
    )
    return result


@api_router.get("/boards/prompts/templates")
async def list_prompt_templates():
    """List available prompt templates from the prompts directory."""
    import os
    from pathlib import Path
    
    prompts_dir = Path(__file__).parent.parent / "prompts"
    templates = []
    
    if prompts_dir.exists():
        for file in prompts_dir.glob("*.md"):
            if file.is_file():
                templates.append(file.stem)
                
    return {"templates": sorted(templates)}

@api_router.get("/boards/{slug}")
async def get_board(slug: str, session: AsyncSession = Depends(get_session)):
    """Get a single board by slug."""
    board = await db_service.get_board_by_slug(session, slug)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return _serialize_board(board)


@api_router.get("/boards/{slug}/perspectives")
async def get_board_perspectives(slug: str, session: AsyncSession = Depends(get_session)):
    """List available perspectives for a board."""
    board = await db_service.get_board_by_slug(session, slug)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    perspectives_data = board.perspectives or {}
    active = perspectives_data.get("active", ["overview"])
    return {"perspectives": active, "default": active[0] if active else "overview"}


@api_router.post("/boards/preview")
async def preview_board_from_payload(
    payload: BoardPreviewRequest,
    session: AsyncSession = Depends(get_session),
):
    """Run preview directly from the current board form payload without saving."""
    _validate_board_source_payload(payload.source_type, payload.source_config)

    from app.models.domain import Board

    base_board = None
    if payload.original_slug:
        base_board = await db_service.get_board_by_slug(session, payload.original_slug)
        if not base_board:
            raise HTTPException(status_code=404, detail=f"Board '{payload.original_slug}' not found.")

    runtime_board = Board(
        id=base_board.id if base_board else None,
        slug=payload.slug,
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        system_prompt=payload.system_prompt,
        source_type=payload.source_type,
        source_config=payload.source_config,
        display_order=base_board.display_order if base_board else 0,
        is_active=base_board.is_active if base_board else True,
        is_default=base_board.is_default if base_board else False,
        schedule=payload.schedule,
        notify_channels=payload.notify_channels,
        perspectives=payload.perspectives,
        prompt_key=payload.prompt_key,
        output_language=payload.output_language,
    )

    return await _run_board_preview_runtime(runtime_board, session, perspective=payload.perspective)


@api_router.post("/boards/{slug}/preview")
async def preview_board(slug: str, session: AsyncSession = Depends(get_session)):
    """
    Run the source adapter and LLM generation for a board without saving to the DB.
    Returns the generated DailySummaryResponse.
    """
    board = await db_service.get_board_by_slug(session, slug)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return await _run_board_preview_runtime(board, session)


@api_router.patch("/boards/{slug}")
async def update_board(
    slug: str,
    payload: BoardUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a board's metadata/config."""
    updates = payload.model_dump(exclude_unset=True)
    existing_board = None
    if "source_type" in updates or ("source_config" in updates and updates["source_config"] is not None):
        existing_board = await db_service.get_board_by_slug(session, slug)
        if not existing_board:
            raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
        effective_source_type = updates.get("source_type", existing_board.source_type)
        effective_source_config = updates.get("source_config", existing_board.source_config)
        _validate_board_source_payload(effective_source_type, effective_source_config)
    board = await db_service.update_board(session, slug, updates)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return _serialize_board(board)


@api_router.delete("/boards/{slug}")
async def delete_board(slug: str, session: AsyncSession = Depends(get_session)):
    """Soft-delete a board (mark inactive). The default board cannot be deleted."""
    ok = await db_service.delete_board(session, slug)
    if not ok:
        board = await db_service.get_board_by_slug(session, slug)
        if board and board.is_default:
            raise HTTPException(status_code=400, detail="The default board cannot be deleted.")
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return {"status": "ok"}


@api_router.get("/history", response_model=SummaryHistoryResponse)
async def get_summary_history(
    limit: int = 7,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """
    Retrieve lightweight archive cards and weekly recap for recent summaries.
    """
    safe_limit = max(1, min(limit, 30))
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None
    return await db_service.get_summary_history(session, limit=safe_limit, board_id=board_id)


@api_router.get("/history/weekly_insight")
async def get_weekly_insight(
    limit: int = 7,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """
    Generate a deep, Wired-style weekly consolidation from recent summaries.
    """
    safe_limit = max(1, min(limit, 10))
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None
    
    # 1. Fetch recent summaries with enough detail
    history = await db_service.get_summary_history(session, limit=safe_limit, board_id=board_id)
    if not history.archive_items:
        raise HTTPException(status_code=404, detail="No history found to summarize.")

    # 2. Re-fetch or pass full data to LLM
    # For now, let's just get the recent dates and fetch full data for those
    summaries_data = []
    for item in history.archive_items:
        full = await db_service.get_summary_by_date(session, item.date, board_id=board_id)
        if full:
            summaries_data.append(full.model_dump())

    if not summaries_data:
        raise HTTPException(status_code=404, detail="Failed to retrieve history content.")

    # 3. Generate consolidation
    insight = await llm_service.generate_weekly_consolidation(
        summaries_data, output_language=getattr(board_obj, "output_language", None)
    )
    if not insight:
        raise HTTPException(status_code=500, detail="Failed to generate weekly insight.")

    return {"weekly_insight": insight}


@api_router.get("/history/weekly_report")
async def get_weekly_report(
    limit: int = 7,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Generate a structured weekly report with themes, stats, and editorial.
    Multi-stage LLM pipeline (fast → fast → smart).
    """
    safe_limit = max(1, min(limit, 10))
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None

    history = await db_service.get_summary_history(session, limit=safe_limit, board_id=board_id)
    if not history.archive_items:
        raise HTTPException(status_code=404, detail="No history found to summarize.")

    summaries_data = []
    for item in history.archive_items:
        full = await db_service.get_summary_by_date(session, item.date, board_id=board_id)
        if full:
            summaries_data.append(full.model_dump())

    if not summaries_data:
        raise HTTPException(status_code=404, detail="Failed to retrieve history content.")

    report = await llm_service.generate_structured_weekly_report(
        summaries_data, output_language=getattr(board_obj, "output_language", None)
    )
    if not report:
        raise HTTPException(status_code=500, detail="Failed to generate weekly report.")

    return report


# ---------------------------------------------------------------------------
# Catch-up Digest & Cache Viewer
# ---------------------------------------------------------------------------


@api_router.get("/catchup/status")
async def get_catchup_status(
    board: Optional[str] = None,
    max_days: int = 7,
    session: AsyncSession = Depends(get_session),
):
    """Lightweight check: how many days are unviewed or missing summaries."""
    safe_days = max(1, min(max_days, 30))
    await _resolve_board(session, board)  # validate slug

    unviewed = await db_service.get_unviewed_dates(session, limit=safe_days)
    gaps = await db_service.get_gap_dates(session, days=safe_days)

    return {
        "unviewed_dates": unviewed,
        "gap_dates": gaps,
        "unviewed_count": len(unviewed),
        "gap_count": len(gaps),
        "earliest_unviewed": unviewed[-1] if unviewed else None,
    }


@api_router.post("/catchup")
async def generate_catchup_digest(
    board: Optional[str] = None,
    max_days: int = 7,
    session: AsyncSession = Depends(get_session),
):
    """Backfill gap days + generate a condensed digest of all unread content."""
    from datetime import timedelta, timezone as _tz

    safe_days = max(1, min(max_days, 14))
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None

    if not board_obj:
        raise HTTPException(status_code=500, detail="No board configured.")

    unviewed = await db_service.get_unviewed_dates(session, limit=safe_days)
    gaps = await db_service.get_gap_dates(session, days=safe_days)

    backfilled_dates: list[str] = []

    # Step 2: Backfill gap dates by expanding the scraper window
    if gaps:
        earliest_gap = gaps[0]
        now = datetime.now(_tz.utc)
        try:
            earliest_dt = datetime.strptime(earliest_gap, "%Y-%m-%d").replace(tzinfo=_tz.utc)
        except ValueError:
            earliest_dt = now
        since_hours = max(24, int((now - earliest_dt).total_seconds() / 3600))

        try:
            from app.services.source_adapters import get_adapter, UnknownSourceTypeError
            adapter = get_adapter(board_obj.source_type)
            summary, content_fallback = await adapter.produce(
                board=board_obj,
                session=session,
                since_hours=since_hours,
            )
            if summary:
                # Save the backfilled summary for ALL gap dates
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

    # Step 3: Collect all unviewed summaries (deduplicate backfilled content)
    all_dates = sorted(set(unviewed + backfilled_dates))
    summaries_data: list[dict] = []
    seen_overviews: set[str] = set()
    for d in all_dates:
        full = await db_service.get_summary_by_date(session, d, board_id=board_id)
        if full:
            overview_key = (full.overview or "")[:80]
            if overview_key and overview_key in seen_overviews:
                continue
            seen_overviews.add(overview_key)
            summaries_data.append(full.model_dump())

    if not summaries_data:
        return {
            "digest": None,
            "dates_covered": [],
            "backfilled_dates": backfilled_dates,
            "total_items": 0,
            "message": "No unread content to digest.",
        }

    # Step 4: Generate condensed digest
    digest = await llm_service.generate_catchup_digest(
        summaries_data, output_language=getattr(board_obj, "output_language", None)
    )

    # Step 5: Mark all covered dates as viewed
    for d in all_dates:
        try:
            await db_service.mark_date_viewed(session, d)
        except Exception:
            pass

    return {
        "digest": digest.model_dump() if digest else None,
        "dates_covered": all_dates,
        "backfilled_dates": backfilled_dates,
        "total_items": len(digest.top_news) if digest else 0,
    }


@api_router.get("/cache")
async def get_cache_overview(
    limit: int = 14,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """All stored summaries with viewed status for cache viewer."""
    safe_limit = max(1, min(limit, 30))
    return await db_service.get_cache_overview(session, limit=safe_limit)
