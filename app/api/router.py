import asyncio
import html as html_mod
import logging
import ssl
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models.schemas import DailySummaryResponse, RSSResponse, SummaryHistoryResponse
from app.prompts import is_prompt_selectable, list_prompt_templates
from app.services.db_service import db_service
from app.services.learning_service import get_inferred_interests, rerank_summary_items
from app.services.dedup_service import normalize_url
from app.services.llm_service import llm_service
from app.services.metrics_service import metrics_service
from app.services.rss_service import fetch_all_feeds
from app.services.email_service import email_service
from app.services.silent_mode_service import (
    get_idle_seconds,
    get_latest_manifest_entry,
    get_manifest_path,
    read_manifest_entries,
    run_silent_collection,
)

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
    catchup_days: int = Field(default=7, ge=0, le=30)


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
    catchup_days: Optional[int] = Field(default=None, ge=0, le=30)


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
    # Optional context for natural-language modification: the most recent
    # suggested config and its validation results, so the LLM can refine rather
    # than start over.
    current_config: Optional[dict] = None
    source_validation: Optional[list[dict]] = None


_summary_generation_lock = asyncio.Lock()

api_router = APIRouter()

@api_router.get("/feed")
async def get_rss_feed(
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Export the last 7 daily summaries as a standard RSS 2.0 XML feed.
    """
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None
    board_slug = board_obj.slug if board_obj else "default"
    board_name = board_obj.name if board_obj else "Argos"
    history = await db_service.get_summary_history(session, limit=7, board_id=board_id)
    
    # We'll use the domain of the first incoming request or just a generic placeholder 
    # since we don't have a configured base URL for the app itself in settings.
    site_url = "https://argos.local"
    
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        '  <channel>',
        f'    <title>{html_mod.escape(board_name)} Daily Briefing</title>',
        f'    <link>{site_url}</link>',
        '    <description>Your personalized daily technology and AI briefing.</description>',
        '    <language>zh-cn</language>'
    ]
    
    from datetime import timezone
    for history_item in history.archive_items:
        summary = await db_service.get_summary_by_date(session, history_item.date, board_id=board_id)
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
        xml.append(f'      <title>{html_mod.escape(f"{board_name} 日报 - {summary.date}")}</title>')
        xml.append(f'      <link>{html_mod.escape(f"{site_url}/?date={summary.date}&board={board_slug}")}</link>')
        xml.append(f'      <guid isPermaLink="false">argos-{html_mod.escape(board_slug)}-{html_mod.escape(summary.date)}</guid>')
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




@api_router.get("/sources/coverage")
async def get_source_coverage_endpoint(
    board: Optional[str] = None,
    date: Optional[str] = None,
    days: int = Query(default=3, ge=2, le=7),
    limit: int = Query(default=6, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
):
    """How different sources covered the same recent stories."""
    from app.services.source_insights_service import get_source_coverage_analysis

    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None
    return await get_source_coverage_analysis(
        session,
        board_id=board_id,
        date=date,
        days=days,
        limit=limit,
    )


@api_router.get("/feeds", response_model=list[RSSResponse])
async def manually_trigger_rss_fetch():
    """
    Manually fetch updates from all configured RSS feeds.
    """
    return await fetch_all_feeds(settings.RSS_FEEDS)


class TestFeedRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)


class ArticleReadRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)
    board: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")


class BoardSourceCreateRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)
    name: str = Field(default="", max_length=200)
    credibility_override: str = Field(
        default="",
        pattern=r"^(|official|established|specialist|community|aggregator|mirror|ai_generated|risky)$",
    )


class BoardSourceUpdateRequest(BaseModel):
    url: Optional[str] = Field(default=None, min_length=5, max_length=2048)
    name: Optional[str] = Field(default=None, max_length=200)
    enabled: Optional[bool] = None
    credibility_override: Optional[str] = Field(
        default=None,
        pattern=r"^(|official|established|specialist|community|aggregator|mirror|ai_generated|risky)$",
    )


class BoardSourceDiscoverRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    limit: int = Field(default=6, ge=1, le=12)


class SilentModeRunRequest(BaseModel):
    force: bool = Field(default=False)


async def _test_single_feed(url: str, timeout: float = 15.0) -> dict:
    """
    Test a single RSS feed URL. Returns a dict with:
      {"url", "ok", "feed_title", "article_count", "sample_titles", "error"}
    Does NOT cache the result. Never raises — failures are returned as ok=False.
    """
    import httpx
    import feedparser

    url = url.strip()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            resp = await client.get(url, timeout=timeout)
            resp.raise_for_status()

        # Pass raw bytes to feedparser so it can detect encoding from XML
        # declaration; resp.text may mis-decode non-UTF-8 feeds.
        feed = feedparser.parse(resp.content)
        entries = feed.entries or []
        feed_title = feed.feed.get("title", "Unknown Feed")

        # Detect feed-level parse errors (e.g. bozo_exception)
        if not entries and hasattr(feed, "bozo_exception"):
            bozo_msg = str(feed.bozo_exception)[:120]
            return {"url": url, "ok": False, "error": f"Feed 解析失败: {bozo_msg}"}

        return {
            "url": url,
            "ok": True,
            "feed_title": feed_title,
            "article_count": len(entries),
            "sample_titles": [e.get("title", "Untitled") for e in entries[:5]],
        }
    except httpx.HTTPStatusError as e:
        return {"url": url, "ok": False, "error": f"HTTP {e.response.status_code}"}
    except httpx.TimeoutException:
        return {"url": url, "ok": False, "error": f"请求超时 ({int(timeout)}s)"}
    except httpx.ConnectError:
        return {"url": url, "ok": False, "error": "连接失败，请检查URL是否正确"}
    except ssl.SSLError as e:
        return {"url": url, "ok": False, "error": f"SSL错误: {str(e)[:100]}"}
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)[:200]}


# Max bytes of homepage HTML to read during RSS autodiscovery — feed <link>
# tags live in <head>, so a small cap is enough and bounds slow/huge pages.
_AUTODISCOVERY_MAX_BYTES = 512 * 1024


async def _discover_feeds(homepage: str, timeout: float = 8.0, limit: int = 4) -> list[str]:
    """Discover RSS/Atom feed URLs advertised by a homepage.

    Fetches *homepage* and parses ``<link rel="alternate"
    type="application/rss+xml|atom+xml">`` tags, resolving relative hrefs to
    absolute URLs. Bounded by *timeout* and ``_AUTODISCOVERY_MAX_BYTES``.
    Never raises — returns ``[]`` on any failure.
    """
    import httpx
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup

    homepage = (homepage or "").strip()
    if not homepage:
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            resp = await client.get(homepage, timeout=timeout)
            resp.raise_for_status()
        html_text = resp.content[:_AUTODISCOVERY_MAX_BYTES].decode(
            resp.encoding or "utf-8", errors="replace"
        )
    except Exception as e:
        logger.debug("autodiscovery fetch failed for %s: %s", homepage, e)
        return []

    return _parse_feed_links(html_text, homepage, limit)


def _parse_feed_links(html_text: str, base_url: str, limit: int = 4) -> list[str]:
    """Parse feed-autodiscovery <link> tags from HTML. Pure; never raises."""
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup

    feed_types = {"application/rss+xml", "application/atom+xml"}
    found: list[str] = []
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        for link in soup.find_all("link"):
            rel = " ".join(link.get("rel") or []).lower()
            ltype = (link.get("type") or "").strip().lower()
            href = (link.get("href") or "").strip()
            if not href or "alternate" not in rel or ltype not in feed_types:
                continue
            absolute = urljoin(base_url, href)
            if absolute not in found:
                found.append(absolute)
            if len(found) >= limit:
                break
    except Exception as e:
        logger.debug("feed-link parse failed for %s: %s", base_url, e)
    return found


@api_router.post("/sources/test")
async def test_source_feed(payload: TestFeedRequest):
    """
    Test a single RSS feed URL. Returns status, article count, and sample titles.
    Does NOT cache the result.
    """
    return await _test_single_feed(payload.url)


@api_router.post("/sources/test_all")
async def test_all_feeds(
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Test all RSS feeds for a given board concurrently.
    Returns a list of results: [{url, ok, feed_title, article_count, error}, ...]
    """
    board_obj = await _resolve_board(session, board)
    if not board_obj:
        raise HTTPException(status_code=404, detail="No board found.")

    feeds = await db_service.get_board_rss_feeds(session, board_obj)

    if not feeds:
        return []

    results = await asyncio.gather(
        *[_test_single_feed(u, timeout=10.0) for u in feeds]
    )
    # Strip sample_titles to keep response small
    return [
        {k: v for k, v in r.items() if k != "sample_titles"}
        for r in results
    ]


@api_router.get("/silent-mode/status")
async def get_silent_mode_status():
    manifest_path = get_manifest_path()
    recent_runs = list(reversed(read_manifest_entries(limit=5)))
    return {
        "enabled": settings.SILENT_MODE_ENABLED,
        "output_dir": settings.SILENT_MODE_OUTPUT_DIR,
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest_path.exists(),
        "last_run": get_latest_manifest_entry(),
        "recent_runs": recent_runs,
        "idle_seconds": get_idle_seconds(),
        "idle_threshold": settings.SILENT_MODE_IDLE_SECONDS,
        "interval_minutes": settings.SILENT_MODE_INTERVAL_MINUTES,
        "lookback_hours": settings.SILENT_MODE_LOOKBACK_HOURS,
        "board_slugs": settings.SILENT_MODE_BOARD_SLUGS,
        "overwrite_today": settings.SILENT_MODE_OVERWRITE_TODAY,
    }


@api_router.post("/silent-mode/run")
async def run_silent_mode(
    payload: SilentModeRunRequest,
    session: AsyncSession = Depends(get_session),
):
    return await run_silent_collection(session, force=payload.force)


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


def _serialize_source(source) -> dict:
    return {
        "id": source.id,
        "url": source.url,
        "name": source.name or "",
        "site_url": getattr(source, "site_url", "") or "",
        "source_type": source.source_type,
        "credibility_override": getattr(source, "credibility_override", "") or "",
        "enabled": bool(source.enabled),
        "board_id": source.board_id,
        "health_status": getattr(source, "health_status", "unknown") or "unknown",
        "last_error": getattr(source, "last_error", "") or "",
        "last_fetched_at": source.last_fetched_at.isoformat() if getattr(source, "last_fetched_at", None) else None,
        "created_at": source.created_at.isoformat() if getattr(source, "created_at", None) else None,
    }


def _build_source_topic(board, source_name: str = "") -> str:
    parts = [
        getattr(board, "name", "") or "",
        getattr(board, "description", "") or "",
        getattr(board, "system_prompt", "") or "",
        source_name or "",
    ]
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())[:500] or "通用资讯"


def _board_supports_rss_sources(board) -> bool:
    return bool(board and board.source_type in {"rss", "multi"})


def _normalize_source_url_or_400(value: str | None) -> str:
    """Normalize a user-submitted RSS URL and reject non-HTTP(S) schemes."""
    from urllib.parse import urlparse

    url = (value or "").strip()
    parsed = urlparse(url)
    if not url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Source URL must be a valid http(s) URL.")
    return url


def _normalize_article_url_or_400(value: str | None) -> str:
    """Normalize an article URL-like identifier while allowing internal schemes."""
    url = (value or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Article URL cannot be empty.")
    return url


def _board_catchup_days(board, default: int = 7) -> int:
    """Return the board catch-up window while preserving 0 as disabled."""
    raw_value = getattr(board, "catchup_days", None)
    if raw_value is None or raw_value == "":
        return default
    try:
        return max(0, min(int(raw_value), 30))
    except (TypeError, ValueError):
        return default


async def _collect_catchup_news(
    session: AsyncSession,
    board_id: int | None,
    catchup_days: int,
    today_str: str,
    exclude_items: list | None = None,
) -> list:
    """Collect unread summary items from recent days as catchup_news.

    ``exclude_items`` lets today's already-rendered articles seed the dedupe
    set so auto-catchup never re-surfaces the same story beside today's news.
    """
    from app.models.schemas import SummaryItem

    def _url_key(url: str) -> str:
        return normalize_url(url).strip().lower() if url else ""

    def _headline_key(headline: str) -> str:
        return (headline or "").strip().lower()[:160]

    if catchup_days <= 0:
        return []

    unread_rows = await db_service.get_unread_summary_items(
        session,
        board_id,
        days=catchup_days,
    )
    unread_rows = [(d, item) for d, item in unread_rows if d != today_str]
    if not unread_rows:
        return []

    catchup_items: list[SummaryItem] = []
    seen_urls: set[str] = set()
    seen_clusters: set[int] = set()
    seen_headlines: set[str] = set()

    for item in exclude_items or []:
        url_key = _url_key(getattr(item, "original_link", ""))
        headline_key = _headline_key(getattr(item, "headline", ""))
        cluster_id = getattr(item, "cluster_id", None)
        if url_key:
            seen_urls.add(url_key)
        if cluster_id:
            seen_clusters.add(int(cluster_id))
        if headline_key:
            seen_headlines.add(headline_key)

    def _quality_score(item) -> int:
        key_points = getattr(item, "key_points", None) or []
        tags = getattr(item, "tags", None) or []
        return len(key_points) * 3 + len(tags) + len(getattr(item, "headline", "") or "")

    unread_rows.sort(key=lambda row: (row[0], _quality_score(row[1])), reverse=True)

    for d, item in unread_rows:
        url = getattr(item, "original_link", "") or ""
        headline = getattr(item, "headline", "") or ""
        cluster_id = getattr(item, "cluster_id", None)
        url_key = _url_key(url)
        headline_key = _headline_key(headline)
        if url_key and url_key in seen_urls:
            continue
        if cluster_id and int(cluster_id) in seen_clusters:
            continue
        if not cluster_id and headline_key and headline_key in seen_headlines:
            continue
        if url_key:
            seen_urls.add(url_key)
        if cluster_id:
            seen_clusters.add(int(cluster_id))
        if headline_key:
            seen_headlines.add(headline_key)
        catchup_items.append(SummaryItem(
            headline=headline,
            category=getattr(item, "category", "general") or "general",
            key_points=getattr(item, "key_points", None) or [],
            tags=getattr(item, "tags", None) or [],
            topic_path=getattr(item, "topic_path", "") or "",
            original_link=url,
            source=getattr(item, "source", "") or "",
            feedback_sentiment=getattr(item, "feedback_sentiment", None),
            persona_score=getattr(item, "persona_score", None),
            is_read=False,
            cluster_id=cluster_id,
            is_catchup=True,
            original_date=d,
        ))

    if not catchup_items:
        return []

    # Strict importance filter — catch-up should only surface high-value items.
    try:
        scored_input = [
            {"headline": ci.headline, "summary": "; ".join(ci.key_points)}
            for ci in catchup_items
        ]
        keep_indices = await llm_service.select_important_catchup_indices(scored_input)
        catchup_items = [ci for i, ci in enumerate(catchup_items) if i in keep_indices]
    except Exception:
        logger.debug("Catchup importance filter skipped; keeping all items")

    return catchup_items


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
        catchup_days = _board_catchup_days(board_obj)
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
        summary.events = await _build_briefing_events(
            session,
            board_id,
            top_news,
            getattr(summary, "date", datetime.now().strftime("%Y-%m-%d")),
        )
    except Exception:
        summary.events = []
        logger.debug("Event track attachment skipped for %s", getattr(summary, "date", "unknown"))


# Guard so overlapping page loads don't trigger duplicate backfill jobs per board.
_catchup_backfill_inflight: set[int] = set()


async def _backfill_gap_days(board_id: int | None, board_slug: str, max_days: int) -> None:
    """Background job: scrape + summarise gap days so auto-catchup can surface them.

    Runs with its own DB session (detached from the request). Best-effort —
    failures are logged but never surface to the caller.
    """
    from datetime import timezone as _tz
    from app.core.db import AsyncSessionLocal
    from app.core.scheduler import track_task_run
    from app.services.source_adapters import get_adapter, UnknownSourceTypeError

    key = board_id if board_id is not None else -1
    if key in _catchup_backfill_inflight:
        return
    _catchup_backfill_inflight.add(key)
    try:
        async with track_task_run("catchup_backfill", trigger_type="auto", board_id=board_id) as tr:
            async with AsyncSessionLocal() as session:
                board_obj = await db_service.get_board_by_id(session, board_id) if board_id else await db_service.get_default_board(session)
                if not board_obj:
                    return
                safe_days = max(1, min(max_days, 14))
                gaps = await db_service.get_gap_dates(session, days=safe_days, board_id=board_id)
                if not gaps:
                    return
                tr.progress_label = f"backfilling {len(gaps)} gap day(s)"

                earliest_gap = gaps[0]
                now = datetime.now(_tz.utc)
                try:
                    earliest_dt = datetime.strptime(earliest_gap, "%Y-%m-%d").replace(tzinfo=_tz.utc)
                except ValueError:
                    earliest_dt = now
                since_hours = max(24, int((now - earliest_dt).total_seconds() / 3600))

                try:
                    adapter = get_adapter(board_obj.source_type)
                    summary, _ = await adapter.produce(
                        board=board_obj, session=session, since_hours=since_hours,
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
                existing_summary.top_news = await rerank_summary_items(
                    existing_summary.top_news,
                    session=session,
                    board_id=board_id,
                )
            except Exception:
                logger.debug("Persona reranking skipped (no feedback data or model not loaded)")
            # Reading the page marks the returned board articles as read.
            try:
                await _mark_items_read(session, existing_summary.top_news, board_id)
            except Exception:
                logger.debug("Article read tracking skipped for %s", search_date)
            # Auto-catchup: attach unviewed items from recent days (only for today's view)
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
            return existing_summary

    # If it's a historical date and not in DB, we don't generate (to save costs/avoid confusion)
    if date and date != datetime.now().strftime("%Y-%m-%d"):
        raise HTTPException(status_code=404, detail=f"No historical summary found for {date}.")

    async with _summary_generation_lock:
        if not force:
            existing_summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id, perspective=perspective)
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
            final.top_news = await rerank_summary_items(
                final.top_news,
                session=session,
                board_id=board_id,
            )
        except Exception:
            logger.debug("Persona reranking skipped for fresh summary")
        # Reading the generated summary marks returned board articles as read.
        try:
            await _mark_items_read(session, final.top_news, board_id)
        except Exception:
            logger.debug("Article read tracking skipped for %s", search_date)
        # Auto-catchup: attach unviewed items from recent days
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
        return final


async def _build_briefing_events(
    session: AsyncSession,
    board_id: int | None,
    root_items: list,
    as_of_date: str,
    *,
    lookback_days: int = 3,
) -> list[dict]:
    cluster_ids: list[int] = []
    for item in root_items or []:
        cluster_id = getattr(item, "cluster_id", None)
        if cluster_id and int(cluster_id) not in cluster_ids:
            cluster_ids.append(int(cluster_id))
    if not cluster_ids:
        return []

    from datetime import timedelta
    from sqlmodel import select
    from app.models.domain import ContentCluster, DailySummary, NewsItem

    try:
        end_date = datetime.strptime(as_of_date, "%Y-%m-%d").date()
        start_str = (end_date - timedelta(days=max(lookback_days - 1, 0))).strftime("%Y-%m-%d")
    except ValueError:
        start_str = as_of_date

    stmt = (
        select(DailySummary.date, NewsItem)
        .join(NewsItem, NewsItem.summary_id == DailySummary.id)
        .where(
            NewsItem.cluster_id.in_(cluster_ids),
            DailySummary.date >= start_str,
            DailySummary.date <= as_of_date,
        )
        .order_by(DailySummary.date.desc(), NewsItem.id.desc())
    )
    if board_id is not None:
        stmt = stmt.where(DailySummary.board_id == board_id)
    result = await session.execute(stmt)
    rows = [(date_value, item) for date_value, item in result.all()]
    if not rows:
        return []

    cluster_result = await session.execute(
        select(ContentCluster).where(ContentCluster.id.in_(cluster_ids))
    )
    clusters_by_id = {cluster.id: cluster for cluster in cluster_result.scalars().all() if cluster.id}
    read_map = await db_service.get_read_state_map(
        session,
        [item.original_link for _, item in rows if item.original_link],
        board_id,
    )

    grouped: dict[int, list[tuple[str, object]]] = {cluster_id: [] for cluster_id in cluster_ids}
    for date_value, item in rows:
        if item.cluster_id in grouped:
            grouped[int(item.cluster_id)].append((date_value, item))

    events: list[dict] = []
    for cluster_id in cluster_ids:
        items = grouped.get(cluster_id) or []
        if not items:
            continue
        cluster = clusters_by_id.get(cluster_id)
        sources: list[str] = []
        event_items: list[dict] = []
        unread_count = 0
        covered_dates: set[str] = set()
        for date_value, item in items:
            covered_dates.add(date_value)
            if item.source and item.source not in sources:
                sources.append(item.source)
            item_is_read = True if not item.original_link else read_map.get(item.original_link, False)
            if not item_is_read:
                unread_count += 1
            if len(event_items) >= 3:
                continue
            event_items.append({
                "date": date_value,
                "headline": item.headline,
                "category": item.category,
                "key_points": item.key_points or [],
                "tags": item.tags or [],
                "topic_path": item.topic_path or "",
                "original_link": item.original_link,
                "source": item.source,
                "cluster_id": cluster_id,
                "is_read": item_is_read,
            })

        latest_date = max(date_value for date_value, _ in items)
        first_date = min(date_value for date_value, _ in items)
        events.append({
            "cluster_id": cluster_id,
            "title": cluster.title if cluster else items[0][1].headline,
            "summary": cluster.summary if cluster else "",
            "item_count": cluster.item_count if cluster else len(items),
            "source_count": len(sources),
            "unread_item_count": unread_count,
            "days_covered": len(covered_dates),
            "first_date": first_date,
            "latest_date": latest_date,
            "sources": sources,
            "items": event_items,
        })
    return events


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

    try:
        await _mark_items_read(session, existing.top_news, board_id)
    except Exception:
        logger.debug("Article read tracking skipped for briefing %s", search_date)

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
            "is_read": getattr(item, "is_read", False),
            "cluster_id": getattr(item, "cluster_id", None),
        })

    # Event-level groups are built from the clusters present in today's briefing.
    events = []
    try:
        events = await _build_briefing_events(session, board_id, existing.top_news, search_date)
    except Exception:
        logger.debug("Briefing event clustering skipped (not yet populated)")

    source_analysis = {"date": search_date, "lookback_days": 3, "items": []}
    try:
        from app.services.source_insights_service import get_source_coverage_analysis
        source_analysis = await get_source_coverage_analysis(
            session,
            board_id=board_id,
            date=search_date,
            days=3,
            limit=4,
        )
    except Exception:
        logger.debug("Source coverage analysis skipped for briefing")

    return {
        "date": existing.date,
        "board": board_obj.slug if board_obj else "default",
        "overview": existing.overview,
        "perspective": existing.perspective,
        "sections": sections,
        "events": events,
        "clusters": events,
        "source_analysis": source_analysis,
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


@api_router.post("/articles/read")
async def mark_article_read_endpoint(
    payload: ArticleReadRequest,
    session: AsyncSession = Depends(get_session),
):
    board_obj = await _resolve_board(session, payload.board)
    url = _normalize_article_url_or_400(payload.url)
    await db_service.mark_article_read(
        session,
        url,
        board_obj.id if board_obj else None,
        is_read=True,
    )
    return {"status": "ok", "is_read": True}


@api_router.delete("/articles/read")
async def mark_article_unread_endpoint(
    payload: ArticleReadRequest,
    session: AsyncSession = Depends(get_session),
):
    board_obj = await _resolve_board(session, payload.board)
    url = _normalize_article_url_or_400(payload.url)
    await db_service.mark_article_read(
        session,
        url,
        board_obj.id if board_obj else None,
        is_read=False,
    )
    return {"status": "ok", "is_read": False}


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
        url = _normalize_article_url_or_400(payload.url)
        await add_saved(
            url,
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
        url = _normalize_article_url_or_400(payload.url)
        await remove_saved(url, payload.status)
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@api_router.get("/persona/inferred")
async def get_inferred_persona(session: AsyncSession = Depends(get_session)):
    """
    Analyze feedback history to infer user interests.
    """
    return await get_inferred_interests(session)


@api_router.get("/persona/training")
async def get_persona_training(
    board: Optional[str] = None,
    limit: int = Query(default=5, ge=1, le=10),
    session: AsyncSession = Depends(get_session),
):
    """Compact training dashboard for the current board's personalization state."""
    from app.services.persona_training_service import get_persona_training_summary

    board_obj = await _resolve_board(session, board) if board is not None else None
    board_id = board_obj.id if board_obj else None
    board_slug = board_obj.slug if board_obj else (board or "default")
    return await get_persona_training_summary(
        session,
        board_id=board_id,
        board_slug=board_slug,
        limit=limit,
    )


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
        "catchup_days": _board_catchup_days(board),
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
    _validate_rss_feed_urls_in_config(source_type, source_config or {})


def _validate_rss_feed_urls_in_config(source_type: str, source_config: dict) -> None:
    """Validate RSS feed URLs embedded in board source_config."""
    if source_type == "rss":
        feeds = source_config.get("feeds") or []
    elif source_type == "multi":
        feeds = (((source_config.get("sources") or {}).get("rss") or {}).get("feeds") or [])
    else:
        return

    for feed_url in feeds:
        if not isinstance(feed_url, str):
            raise HTTPException(status_code=400, detail="RSS feed URLs must be strings.")
        _normalize_source_url_or_400(feed_url)


def _validate_board_prompt_key_or_400(prompt_key: str | None) -> str:
    """Validate that ``prompt_key`` refers to an existing, user-selectable
    ``board_summary`` template.  Normalise empty / None to ``"daily_briefing"``
    and raise HTTP 400 on invalid keys.
    """
    key = (prompt_key or "").strip() or "daily_briefing"
    if not is_prompt_selectable(key):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Prompt key '{key}' is not a valid board summary template. "
                "Choose a template from GET /boards/prompts/templates."
            ),
        )
    return key


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
    payload.prompt_key = _validate_board_prompt_key_or_400(payload.prompt_key)
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
        catchup_days=payload.catchup_days,
    )
    if _board_supports_rss_sources(board):
        board = await db_service.sync_board_rss_sources(session, board)
    return _serialize_board(board)


async def _probe_url(
    source_type: str,
    label: str,
    url: str,
    timeout: float,
    headers: dict | None = None,
) -> dict:
    """Lightweight reachability probe for a single non-RSS source target."""
    import httpx

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            resp = await client.get(url, timeout=timeout)
            resp.raise_for_status()
        return {"source_type": source_type, "label": label, "url": url, "ok": True}
    except httpx.HTTPStatusError as e:
        return {"source_type": source_type, "label": label, "url": url, "ok": False, "error": f"HTTP {e.response.status_code}"}
    except httpx.TimeoutException:
        return {"source_type": source_type, "label": label, "url": url, "ok": False, "error": f"请求超时 ({int(timeout)}s)"}
    except httpx.ConnectError:
        return {"source_type": source_type, "label": label, "url": url, "ok": False, "error": "连接失败"}
    except Exception as e:
        return {"source_type": source_type, "label": label, "url": url, "ok": False, "error": str(e)[:120]}


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "Argos-Wizard"}
    token = getattr(settings, "GITHUB_TOKEN", None)
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


_REDDIT_PROBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


async def _count_via_scraper(source_type: str, cfg: dict, since_hours: int = 168) -> list:
    """Run the relevant scraper for a single-target config and return ContentItems."""
    from datetime import timedelta, timezone

    from app.core.http_client import get_http_client

    client = get_http_client()
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    scraper_cfg = {"enabled": True, **cfg}

    if source_type == "hackernews":
        from app.scrapers.hackernews import HackerNewsScraper
        scraper = HackerNewsScraper(scraper_cfg, client)
    elif source_type == "reddit":
        from app.scrapers.reddit import RedditScraper
        scraper = RedditScraper(scraper_cfg, client)
    elif source_type == "github":
        from app.scrapers.github import GitHubScraper
        scraper = GitHubScraper(scraper_cfg, client)
    else:
        return []
    try:
        return await scraper.fetch(since)
    except Exception as error:
        logger.warning("preview scraper '%s' failed: %s", source_type, error)
        return []


async def _enrich_deep(entry: dict, source_type: str, cfg: dict) -> dict:
    """When deep=True and the source is reachable, attach article_count + samples."""
    if not entry.get("ok"):
        return entry
    items = await _count_via_scraper(source_type, cfg)
    entry["article_count"] = len(items)
    entry["sample_titles"] = [getattr(i, "title", "Untitled") for i in items[:5]]
    return entry


async def _validate_source_group(
    source_type: str,
    cfg: dict,
    timeout: float,
    deep: bool,
) -> list[dict]:
    """Validate one source-type config block; returns a list of per-target entries."""
    cfg = cfg or {}

    if source_type == "rss":
        feeds = [u for u in (cfg.get("feeds") or []) if isinstance(u, str) and u.strip()]
        if not feeds:
            return []
        results = await asyncio.gather(*[_test_single_feed(u, timeout=timeout) for u in feeds])
        return [
            {
                "source_type": "rss",
                "label": r.get("url"),
                "url": r.get("url"),
                "ok": r.get("ok", False),
                "article_count": r.get("article_count", 0),
                "feed_title": r.get("feed_title"),
                "sample_titles": r.get("sample_titles", []),
                "error": r.get("error"),
            }
            for r in results
        ]

    if source_type == "hackernews":
        entry = await _probe_url(
            "hackernews", "Hacker News",
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout,
        )
        if deep:
            entry = await _enrich_deep(entry, "hackernews", cfg)
        return [entry]

    if source_type == "github":
        tasks = []
        for repo in cfg.get("repos", []):
            owner = (repo or {}).get("owner", "")
            name = (repo or {}).get("repo", "")
            if not owner or not name:
                continue
            label = f"{owner}/{name}"
            tasks.append(("github", label, f"https://api.github.com/repos/{owner}/{name}", {"repos": [repo]}))
        for user in cfg.get("users", []):
            uname = user.get("username", "") if isinstance(user, dict) else str(user)
            if not uname:
                continue
            single = user if isinstance(user, dict) else {"username": uname}
            tasks.append(("github", uname, f"https://api.github.com/users/{uname}", {"users": [single]}))
        gh_headers = _github_headers()
        entries = await asyncio.gather(
            *[_probe_url(st, label, url, timeout, headers=gh_headers) for st, label, url, _ in tasks]
        )
        entries = list(entries)
        if deep:
            entries = await asyncio.gather(
                *[_enrich_deep(e, "github", sub_cfg) for e, (_, _, _, sub_cfg) in zip(entries, tasks)]
            )
        return list(entries)

    if source_type == "pure_llm":
        return [{"source_type": "pure_llm", "label": "纯 LLM 生成", "ok": True, "article_count": 0, "sample_titles": []}]

    if source_type == "reddit":
        tasks = []
        for sub in cfg.get("subreddits", []):
            name = sub.get("subreddit", "") if isinstance(sub, dict) else str(sub)
            if not name:
                continue
            single = {"subreddits": [sub if isinstance(sub, dict) else {"subreddit": name}]}
            tasks.append(("reddit", f"r/{name}", f"https://www.reddit.com/r/{name}/about.json", single))
        for user in cfg.get("users", []):
            uname = user.get("username", "") if isinstance(user, dict) else str(user)
            if not uname:
                continue
            single = {"users": [user if isinstance(user, dict) else {"username": uname}]}
            tasks.append(("reddit", f"u/{uname}", f"https://www.reddit.com/user/{uname}/about.json", single))
        entries = await asyncio.gather(
            *[_probe_url(st, label, url, timeout, headers=_REDDIT_PROBE_HEADERS) for st, label, url, _ in tasks]
        )
        entries = list(entries)
        if deep:
            entries = await asyncio.gather(
                *[_enrich_deep(e, "reddit", sub_cfg) for e, (_, _, _, sub_cfg) in zip(entries, tasks)]
            )
        return list(entries)

    return []


async def _validate_config_sources(
    config: dict | None,
    timeout: float = 8.0,
    deep: bool = False,
) -> list[dict]:
    """
    Validate every source declared by a wizard config, including each sub-source
    of a ``multi`` board. Returns a flat list of per-target validation entries.
    When ``deep`` is True, reachable non-RSS targets are additionally fetched to
    report ``article_count`` and ``sample_titles``.
    """
    if not config:
        return []
    source_type = config.get("source_type")
    source_config = config.get("source_config") or {}

    if source_type == "multi":
        groups = source_config.get("sources") or {}
        results = await asyncio.gather(
            *[_validate_source_group(st, gcfg, timeout, deep) for st, gcfg in groups.items()]
        )
        return [entry for group in results for entry in group]

    return await _validate_source_group(source_type, source_config, timeout, deep)


def _derive_feed_validation(source_validation: list[dict]) -> list[dict] | None:
    """Extract RSS entries in the legacy feed_validation shape for the frontend."""
    feeds = [e for e in source_validation if e.get("source_type") == "rss"]
    if not feeds:
        return None
    return [
        {
            "url": e.get("url"),
            "ok": e.get("ok", False),
            "feed_title": e.get("feed_title"),
            "article_count": e.get("article_count", 0),
            "sample_titles": e.get("sample_titles", []),
            "error": e.get("error"),
        }
        for e in feeds
    ]


def _serialize_source_quality_report(review: dict | None, limit: int = 5) -> dict | None:
    if not review:
        return None
    selected = list(review.get("selected") or [])
    dropped = list(review.get("dropped") or [])
    return {
        "summary": review.get("summary", ""),
        "safe_count": review.get("safe_count", 0),
        "selected_count": len(selected),
        "dropped_count": len(dropped),
        "selected": selected[:limit],
        "dropped": dropped[:limit],
    }


# Target number of reachable RSS feeds before the self-correction loop stops.
_DISCOVERY_RSS_TARGET = 3
_DISCOVERY_MAX_FIX_ROUNDS = 2


async def _discover_rss_candidates(plan: dict) -> list[str]:
    """Find candidate RSS feed URLs from search terms + homepage hints (no LLM URLs).

    Discovery chain:
      1. Tavily search → autodiscover ``<link rel=alternate>`` on each result site.
      2. Fallback for sites with no advertised feed (common for Chinese sources):
         probe common feed paths (/feed, /rss, ...) on each homepage.
      3. RSSHub: build standard-RSS URLs from planner-supplied platform identifiers
         (公众号/知乎/B站/即刻 ... have no native RSS but RSSHub generates it).
    Returns a deduplicated list of candidate feed URLs (unvalidated).
    """
    from app.services.research_service import tavily_search

    homepages: list[str] = list(plan.get("homepage_hints") or [])
    for term in plan.get("search_terms") or []:
        try:
            results = await tavily_search(term, max_results=4)
        except Exception as e:
            logger.debug("wizard discovery search failed for '%s': %s", term, e)
            continue
        for r in results:
            url = r.get("url")
            if url and url not in homepages:
                homepages.append(url)

    feeds: list[str] = []

    def _add(url: str) -> None:
        if url and url not in feeds:
            feeds.append(url)

    # 0. Curated catalog: known-good feeds by topic, before any network search.
    #    Zero network cost; URLs still get validated by _verify_and_fix_feeds.
    from app.services.feed_catalog import catalog_candidate_urls

    for url in catalog_candidate_urls(plan):
        _add(url)

    # 1. Autodiscover advertised feeds from every candidate homepage, concurrently.
    discovered = await asyncio.gather(*[_discover_feeds(h) for h in homepages])
    homepages_without_feed = []
    for homepage, group in zip(homepages, discovered):
        if group:
            for f in group:
                _add(f)
        else:
            homepages_without_feed.append(homepage)

    # 2. Fallback: probe common feed paths on homepages that advertised nothing.
    if homepages_without_feed:
        probed = await asyncio.gather(*[_probe_common_feed_paths(h) for h in homepages_without_feed])
        for group in probed:
            for f in group:
                _add(f)

    # 3. RSSHub: construct standard-RSS URLs from planner platform identifiers.
    for url in _rsshub_candidate_urls(plan):
        _add(url)

    return feeds


# Common feed paths to probe when a site advertises no <link rel=alternate>.
_COMMON_FEED_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml")


async def _probe_common_feed_paths(homepage: str, limit: int = 2) -> list[str]:
    """Try well-known feed paths on a homepage root; return reachable feed URLs.

    Bounded to *limit* hits. Never raises. Used as a fallback when autodiscovery
    finds nothing (common for sites that don't advertise their feed in <head>).
    """
    from urllib.parse import urlsplit, urlunsplit

    homepage = (homepage or "").strip()
    if not homepage:
        return []
    try:
        parts = urlsplit(homepage)
        if not parts.scheme or not parts.netloc:
            return []
        root = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    except Exception:
        logger.debug("URL root extraction failed for homepage: %s", homepage)
        return []

    found: list[str] = []
    results = await asyncio.gather(
        *[_test_single_feed(root + path, timeout=6.0) for path in _COMMON_FEED_PATHS]
    )
    for r in results:
        if r.get("ok"):
            found.append(r["url"])
            if len(found) >= limit:
                break
    return found


def _rsshub_candidate_urls(plan: dict) -> list[str]:
    """Build RSSHub feed URLs from the planner's ``candidates.rsshub`` entries.

    Each entry is ``{platform, ...params}``. Gated behind ``RSSHUB_ENABLED``.
    Unknown platforms / missing params are skipped (build returns None).
    """
    if not getattr(settings, "RSSHUB_ENABLED", True):
        return []
    entries = ((plan.get("candidates") or {}).get("rsshub")) or []
    if not entries:
        return []
    from app.services.rsshub import build_rsshub_url

    urls: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        platform = entry.get("platform")
        params = {k: v for k, v in entry.items() if k != "platform"}
        url = build_rsshub_url(platform, **params)
        if url and url not in urls:
            urls.append(url)
    return urls


def _plan_to_nonrss_config(plan: dict) -> dict:
    """Build a source_config block for the non-RSS source types that don't need
    search (hackernews / pure_llm). Reddit & GitHub are populated from real
    platform search in ``discover_and_verify``, not here."""
    st = plan["source_type"]
    if st == "hackernews":
        return {"fetch_top_stories": 30, "min_score": 100}
    return {}


async def _discover_reddit_config(plan: dict, limit: int = 5) -> dict:
    """Search real subreddits from the plan's search terms → reddit source_config.

    Search terms run concurrently; results are deduped in term order so the
    output is deterministic for a given plan.
    """
    from app.services.source_search import search_subreddits

    terms = plan.get("search_terms") or [plan.get("name", "")]
    per_term = await asyncio.gather(*[search_subreddits(t, limit=limit) for t in terms])
    seen: set[str] = set()
    subs: list[dict] = []
    for hits in per_term:
        for hit in hits:
            name = hit["name"]
            if name and name.lower() not in seen:
                seen.add(name.lower())
                subs.append({"subreddit": name, "min_score": 50})
    return {"subreddits": subs[:limit], "fetch_comments": 5}


async def _discover_github_config(plan: dict, limit: int = 5) -> dict:
    """Search real GitHub repos from the plan's search terms → github source_config.

    Repos only — the search API finds repositories, not user accounts, so
    user-event tracking is not auto-discovered (a known limitation). Search
    terms run concurrently; results are deduped in term order.
    """
    from app.services.source_search import search_github_repos

    terms = plan.get("search_terms") or [plan.get("name", "")]
    per_term = await asyncio.gather(*[search_github_repos(t, limit=limit) for t in terms])
    seen: set[str] = set()
    repos: list[dict] = []
    for hits in per_term:
        for hit in hits:
            key = f"{hit['owner']}/{hit['repo']}".lower()
            if key not in seen:
                seen.add(key)
                repos.append({"owner": hit["owner"], "repo": hit["repo"]})
    return {"repos": repos[:limit], "users": []}


async def discover_and_verify(plan: dict) -> dict:
    """Pipeline stages ②③: discover real sources and verify reachability.

    Returns a *verified pool* describing only reachable sources, plus the raw
    validation entries (with sample_titles) for the finalize stage to choose
    from. Reddit/GitHub use real platform search; RSS uses the discovery chain
    (Tavily + autodiscovery + common paths + RSSHub). Never raises.
    """
    st = plan["source_type"]
    cand = plan.get("candidates") or {}
    pool: dict = {"source_type": st, "verified": [], "rss_feeds": []}

    if st in ("rss", "multi"):
        candidates = await _discover_rss_candidates(plan)
        verified = await _verify_and_fix_feeds(candidates, plan)
        pool["rss_feeds"] = verified
        pool["verified"].extend(verified)

    # Probe each non-RSS source type only when actually requested. For a
    # single-type board the type itself is the intent; for "multi" we gate on
    # the planner's signals (hackernews flag, search_terms for reddit/github)
    # so we never silently attach a source the planner never proposed.
    has_terms = bool(plan.get("search_terms"))
    want_hn = st == "hackernews" or (st == "multi" and cand.get("hackernews"))
    want_reddit = st == "reddit" or (st == "multi" and has_terms)
    want_github = st == "github" or (st == "multi" and has_terms)

    if want_hn:
        cfg = _plan_to_nonrss_config({**plan, "source_type": "hackernews"})
        entries = await _validate_source_group("hackernews", cfg, timeout=8.0, deep=True)
        pool["verified"].extend([e for e in entries if e.get("ok")])

    if want_reddit:
        cfg = await _discover_reddit_config(plan)
        if cfg.get("subreddits"):
            entries = await _validate_source_group("reddit", cfg, timeout=8.0, deep=True)
            pool["verified"].extend([e for e in entries if e.get("ok")])

    if want_github:
        cfg = await _discover_github_config(plan)
        if cfg.get("repos"):
            entries = await _validate_source_group("github", cfg, timeout=8.0, deep=True)
            pool["verified"].extend([e for e in entries if e.get("ok")])

    if st == "pure_llm":
        pool["verified"] = [{"source_type": "pure_llm", "ok": True}]

    try:
        from app.services.source_insights_service import annotate_source_validation, review_source_candidates

        reviewed = review_source_candidates(annotate_source_validation(pool["verified"]))
        pool["verified"] = reviewed["selected"]
        pool["source_quality_report"] = _serialize_source_quality_report(reviewed)
    except Exception:
        logger.debug("Wizard source-quality annotation skipped")

    return pool


async def _verify_and_fix_feeds(candidates: list[str], plan: dict) -> list[dict]:
    """Validate RSS candidates; if too few reachable, ask LLM for alternatives
    and re-validate. Bounded by ``_DISCOVERY_MAX_FIX_ROUNDS``. Returns reachable
    feed entries only (deep=True so sample_titles are populated)."""
    if not candidates:
        candidates = []
    verified: list[dict] = []
    seen: set[str] = set()

    async def _validate(urls: list[str]) -> list[dict]:
        fresh = [u for u in urls if u and u not in seen]
        for u in fresh:
            seen.add(u)
        if not fresh:
            return []
        results = await asyncio.gather(*[_test_single_feed(u, timeout=8.0) for u in fresh])
        ok = [r for r in results if r.get("ok")]
        return [{"source_type": "rss", "label": r["url"], **r} for r in ok]

    verified.extend(await _validate(candidates))

    topic = f"{plan.get('name', '')} {plan.get('intent', '')}".strip()
    rounds = 0
    while len(verified) < _DISCOVERY_RSS_TARGET and rounds < _DISCOVERY_MAX_FIX_ROUNDS:
        rounds += 1
        broken = [u for u in seen][:10] or [topic]
        try:
            alts = await llm_service.suggest_alternative_feeds(topic=topic or "通用资讯", broken_urls=broken)
        except Exception as e:
            logger.debug("wizard feed-fix round %d failed: %s", rounds, e)
            break
        new_urls = [u for grp in alts for u in grp.get("suggestions", [])]
        if not new_urls:
            break
        verified.extend(await _validate(new_urls))

    if len(verified) < _DISCOVERY_RSS_TARGET:
        logger.info(
            "wizard discovery: only %d/%d RSS feeds reachable after %d fix round(s)",
            len(verified), _DISCOVERY_RSS_TARGET, rounds,
        )
    return verified


@api_router.post("/boards/wizard")
async def board_wizard(payload: BoardWizardRequest):
    """
    Interactive AI-guided wizard to help users configure a new board.
    Accepts a conversation history, returns a reply plus (when ready) a suggested config.
    Every declared source (including ``multi`` sub-sources) is validated and the
    results are attached under ``source_validation``; RSS entries are also exposed
    under ``feed_validation`` for backward compatibility.
    """
    context = None
    if payload.current_config or payload.source_validation:
        context = {
            "current_config": payload.current_config,
            "source_validation": payload.source_validation,
        }

    messages = [m.model_dump() for m in payload.messages]

    if getattr(settings, "WIZARD_PIPELINE_ENABLED", True):
        return await _run_wizard_pipeline(messages, context)

    # Legacy single-call path (flag off).
    result = await llm_service.wizard_suggest_board(messages, context=context)
    if result.get("ready") and result.get("config"):
        source_validation = await _validate_config_sources(result["config"])
        if source_validation:
            try:
                from app.services.source_insights_service import annotate_source_validation
                source_validation = annotate_source_validation(source_validation)
            except Exception:
                logger.debug("Wizard source-quality annotation skipped")
            result["source_validation"] = source_validation
            feed_validation = _derive_feed_validation(source_validation)
            if feed_validation is not None:
                result["feed_validation"] = feed_validation
    return result


async def _run_wizard_pipeline(messages: list[dict], context: dict | None) -> dict:
    """Multi-stage grounded wizard: plan → discover+verify → finalize → preview.

    Returns the same response shape as the legacy path
    ({reply, ready, config, source_validation?, feed_validation?}) so the
    frontend needs no changes.
    """
    # ① intent + source strategy (fast)
    plan = await llm_service.wizard_plan_sources(messages, context=context)
    if not plan.get("ready"):
        return {
            "reply": plan.get("clarify") or "可以再具体描述一下你想要的内容吗？",
            "ready": False,
            "config": None,
        }

    # ②③ discover real sources + verify + self-correct
    pool = await discover_and_verify(plan)

    # ④ choose from the verified pool + write the system prompt (smart)
    final = await llm_service.wizard_finalize(plan, pool)
    config = final.get("config")
    reply = final.get("reply") or ""
    if not config:
        return {"reply": reply or "暂时没能生成可用配置，换个描述再试试？", "ready": False, "config": None}

    # ⑤ preview: deep-validate the final config for reachability + sample titles
    source_validation = await _validate_config_sources(config, deep=True)
    result = {"reply": reply, "ready": True, "config": config}
    if pool.get("source_quality_report"):
        result["source_discovery_report"] = pool["source_quality_report"]
    if source_validation:
        try:
            from app.services.source_insights_service import annotate_source_validation
            source_validation = annotate_source_validation(source_validation)
        except Exception:
            logger.debug("Wizard source-quality annotation skipped")
        result["source_validation"] = source_validation
        feed_validation = _derive_feed_validation(source_validation)
        if feed_validation is not None:
            result["feed_validation"] = feed_validation
    return result


class WizardPreviewRequest(BaseModel):
    config: dict


@api_router.post("/boards/wizard/preview")
async def wizard_preview(payload: WizardPreviewRequest):
    """
    Preview the fetch result of a wizard config without running the LLM summary.
    Returns per-source reachability, article counts, and sample titles so the
    user can judge whether each source (including ``multi`` sub-sources) works.
    """
    config = payload.config or {}
    sources = await _validate_config_sources(config, timeout=12.0, deep=True)
    quality_report = None
    try:
        from app.services.source_insights_service import annotate_source_validation, review_source_candidates
        sources = annotate_source_validation(sources)
        quality_report = review_source_candidates(sources, min_non_risky=2)
    except Exception:
        logger.debug("Wizard source-quality annotation skipped")
    total = sum((s.get("article_count") or 0) for s in sources)
    ok = any(s.get("ok") for s in sources) if sources else False
    return {
        "ok": ok,
        "sources": sources,
        "total_articles": total,
        "quality_report": _serialize_source_quality_report(quality_report),
    }


class FixFeedsRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    broken_urls: list[str] = Field(min_length=1, max_length=10)


@api_router.post("/boards/wizard/fix-feeds")
async def wizard_fix_feeds(payload: FixFeedsRequest):
    """
    For each broken RSS URL, ask the LLM to propose alternative feeds for the
    given topic, validate the candidates, and return them grouped by original.
    """
    broken = [u.strip() for u in payload.broken_urls if u and u.strip()]
    if not broken:
        return {"alternatives": []}

    candidates = await llm_service.suggest_alternative_feeds(
        topic=payload.topic,
        broken_urls=broken,
    )

    # Validate all unique candidate URLs concurrently.
    all_urls: list[str] = []
    for group in candidates:
        for url in group.get("suggestions", []):
            if url not in all_urls:
                all_urls.append(url)

    validation_map: dict[str, dict] = {}
    if all_urls:
        results = await asyncio.gather(
            *[_test_single_feed(u, timeout=8.0) for u in all_urls]
        )
        try:
            from app.services.source_insights_service import annotate_source_validation

            results = annotate_source_validation(
                [
                    {
                        "source_type": "rss",
                        "label": r.get("feed_title") or r.get("url"),
                        **r,
                    }
                    for r in results
                ]
            )
        except Exception:
            logger.debug("Wizard feed-fix source-quality annotation skipped")
        validation_map = {r["url"]: r for r in results}

    alternatives = []
    for group in candidates:
        original = group.get("original", "")
        group_entries = [
            validation_map[url]
            for url in group.get("suggestions", [])
            if url in validation_map
        ]
        try:
            from app.services.source_insights_service import review_source_candidates

            review = review_source_candidates(group_entries, min_non_risky=2)
            suggestions = review["selected"]
            discarded = review["dropped"]
            quality_report = _serialize_source_quality_report(review)
        except Exception:
            logger.debug("Wizard feed-fix source-quality review skipped")
            suggestions = [entry for entry in group_entries if entry.get("ok")]
            discarded = [entry for entry in group_entries if not entry.get("ok")]
            quality_report = None
        alternatives.append(
            {
                "original": original,
                "suggestions": suggestions,
                "discarded_suggestions": discarded,
                "quality_report": quality_report,
            }
        )

    return {"alternatives": alternatives}


@api_router.get("/boards/prompts/templates")
async def list_prompt_templates():
    """List prompt templates available for board summary generation.

    Only returns templates whose frontmatter declares
    ``type: board_summary`` and ``user_selectable: true``.
    Internal pipeline templates (scoring, wizard, research, etc.) are excluded.
    """
    selectable = list_prompt_templates(
        template_type="board_summary",
        user_selectable=True,
    )
    return {
        "templates": [m["key"] for m in selectable],
        "items": [
            {
                "key": m["key"],
                "name": m.get("name", m["key"]),
                "description": m.get("description", ""),
                "version": m.get("version", ""),
                "type": m.get("type", "board_summary"),
            }
            for m in selectable
        ],
    }

@api_router.post("/boards/prompts/render")
async def render_prompt_preview(
    payload: BoardPreviewRequest,
    session: AsyncSession = Depends(get_session),
):
    """Render the resolved system prompt for a board configuration without
    calling the LLM — useful for inspecting how template variables,
    custom instructions, schema directives, and language settings combine.

    Returns the effective system message content along with a sample user
    message template and a rough character count.
    """
    from app.models.domain import Board
    from app.services.llm.summary import build_summary_prompt_preview

    runtime_board = Board(
        slug=payload.slug,
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        system_prompt=payload.system_prompt,
        source_type=payload.source_type,
        source_config=payload.source_config,
        schedule=payload.schedule,
        notify_channels=payload.notify_channels,
        perspectives=payload.perspectives,
        prompt_key=_validate_board_prompt_key_or_400(payload.prompt_key),
        output_language=payload.output_language,
    )

    # Gather active personas for preview context
    persona_preview = ""
    if payload.original_slug:
        try:
            board_obj = await db_service.get_board_by_slug(session, payload.original_slug)
            if board_obj:
                personas = await db_service.get_active_personas(session, board_id=board_obj.id)
                if personas:
                    lines = [f"- [{p.category}] {p.content}" for p in personas]
                    persona_preview = "USER PERSONALITY & PREFERENCE GUIDELINES:\n" + "\n".join(lines)
        except Exception:
            pass  # Persona fetch is best-effort for preview

    preview = build_summary_prompt_preview(
        runtime_board,
        persona_context=persona_preview,
    )

    from app.prompts import get_prompt_metadata
    meta = get_prompt_metadata(runtime_board.prompt_key or "daily_briefing")

    return {
        "prompt_key": runtime_board.prompt_key,
        "template": {
            "key": meta.get("key", runtime_board.prompt_key),
            "name": meta.get("name", ""),
            "version": meta.get("version", ""),
        },
        "messages": [
            {"role": "system", "content": preview["system_prompt"]},
            {"role": "user", "content": preview["user_prompt_template"]},
        ],
        "warnings": [],
        "estimated_chars": len(preview["system_prompt"]),
    }


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
    payload.prompt_key = _validate_board_prompt_key_or_400(payload.prompt_key)

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
    # Validate prompt_key if present in the update
    if "prompt_key" in updates and updates["prompt_key"] is not None:
        updates["prompt_key"] = _validate_board_prompt_key_or_400(updates["prompt_key"])
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
    if _board_supports_rss_sources(board) and (
        "source_type" in updates or "source_config" in updates
    ):
        board = await db_service.sync_board_rss_sources(session, board)
    return _serialize_board(board)


@api_router.get("/boards/{slug}/sources")
async def list_board_sources_endpoint(
    slug: str,
    session: AsyncSession = Depends(get_session),
):
    board = await _resolve_board(session, slug)
    if not _board_supports_rss_sources(board):
        return []
    sources = await db_service.list_board_sources(session, board.id, "rss", enabled_only=True)
    return [_serialize_source(source) for source in sources]


@api_router.post("/boards/{slug}/sources")
async def add_board_source_endpoint(
    slug: str,
    payload: BoardSourceCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    board = await _resolve_board(session, slug)
    if not _board_supports_rss_sources(board):
        raise HTTPException(status_code=400, detail="P0 source management only supports RSS sources.")
    url = _normalize_source_url_or_400(payload.url)
    source = await db_service.add_board_source(
        session,
        board,
        url,
        name=payload.name.strip(),
        credibility_override=payload.credibility_override.strip(),
    )
    return _serialize_source(source)


@api_router.post("/boards/{slug}/sources/discover")
async def discover_board_sources_endpoint(
    slug: str,
    payload: BoardSourceDiscoverRequest,
    session: AsyncSession = Depends(get_session),
):
    """Discover and validate candidate RSS sources for the current board topic."""
    from app.services.source_insights_service import annotate_source_validation, review_source_candidates

    board = await _resolve_board(session, slug)
    if not _board_supports_rss_sources(board):
        raise HTTPException(status_code=400, detail="P0 source management only supports RSS sources.")

    existing_urls = await db_service.get_board_rss_feeds(session, board)
    existing_set = {url.strip() for url in existing_urls if isinstance(url, str) and url.strip()}
    topic = (payload.query or "").strip() or _build_source_topic(board)

    try:
        plan = await llm_service.wizard_plan_sources(
            [{"role": "user", "content": f"请为这个主题寻找高质量 RSS 来源：{topic}"}]
        )
    except Exception:
        logger.debug("Board source discovery planner fallback for '%s'", slug)
        plan = {}

    search_terms = [term for term in (plan.get("search_terms") or []) if isinstance(term, str) and term.strip()]
    if topic and topic not in search_terms:
        search_terms.insert(0, topic)

    discovery_plan = {
        "ready": True,
        "source_type": "rss",
        "name": board.name or topic,
        "intent": topic,
        "search_terms": search_terms[:6] or [topic],
        "homepage_hints": [url for url in (plan.get("homepage_hints") or []) if isinstance(url, str) and url.strip()][:6],
        "candidates": dict(plan.get("candidates") or {}),
    }
    discovery_plan["candidates"].pop("hackernews", None)

    candidates = await _discover_rss_candidates(discovery_plan)
    verified = await _verify_and_fix_feeds(candidates, discovery_plan)

    fresh_verified: list[dict] = []
    skipped_existing: list[str] = []
    for entry in verified:
        url = (entry.get("url") or "").strip()
        if not url:
            continue
        if url in existing_set:
            skipped_existing.append(url)
            continue
        fresh_verified.append(entry)

    annotated = annotate_source_validation(fresh_verified)
    review = review_source_candidates(annotated, min_non_risky=2)
    limit = int(payload.limit or 6)
    return {
        "topic": topic,
        "summary": review["summary"] if annotated else "No validated RSS candidates were found for this board yet.",
        "searched_terms": discovery_plan["search_terms"],
        "homepage_hints": discovery_plan["homepage_hints"],
        "suggestions": review["selected"][:limit],
        "discarded_suggestions": review["dropped"][:limit],
        "skipped_existing": skipped_existing[:limit],
        "existing_source_count": len(existing_set),
    }


@api_router.patch("/boards/{slug}/sources/{source_id}")
async def update_board_source_endpoint(
    slug: str,
    source_id: int,
    payload: BoardSourceUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    board = await _resolve_board(session, slug)
    if not _board_supports_rss_sources(board):
        raise HTTPException(status_code=400, detail="P0 source management only supports RSS sources.")
    url = _normalize_source_url_or_400(payload.url) if payload.url is not None else None
    source = await db_service.update_board_source(
        session,
        board,
        source_id,
        url=url,
        name=payload.name.strip() if payload.name is not None else None,
        enabled=payload.enabled,
        credibility_override=payload.credibility_override,
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found.")
    return _serialize_source(source)


@api_router.get("/boards/{slug}/sources/{source_id}/alternatives")
async def get_board_source_alternatives_endpoint(
    slug: str,
    source_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Suggest and validate safer RSS replacements for one board source."""
    from sqlmodel import select
    from app.models.domain import Source
    from app.services.source_insights_service import (
        annotate_source_validation,
        review_source_candidates,
        score_source_quality,
        summarize_source_risk,
    )

    board = await _resolve_board(session, slug)
    if not _board_supports_rss_sources(board):
        raise HTTPException(status_code=400, detail="P0 source management only supports RSS sources.")

    result = await session.execute(
        select(Source).where(
            Source.id == source_id,
            Source.board_id == board.id,
            Source.source_type == "rss",
        )
    )
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found.")

    serialized = _serialize_source(source)
    serialized.update(
        score_source_quality(
            url=serialized["url"],
            source_type=serialized["source_type"],
            credibility_override=serialized["credibility_override"],
            health_status=serialized["health_status"],
        )
    )
    source_snapshot = {
        **serialized,
        **summarize_source_risk(serialized),
    }

    topic = _build_source_topic(board, source.name or source.url)
    raw_groups = await llm_service.suggest_alternative_feeds(topic=topic, broken_urls=[source.url])
    candidate_urls: list[str] = []
    for group in raw_groups or []:
        for candidate in group.get("suggestions", []):
            if candidate and candidate not in candidate_urls:
                candidate_urls.append(candidate)

    validation_entries: list[dict] = []
    if candidate_urls:
        tested = await asyncio.gather(*[_test_single_feed(url, timeout=8.0) for url in candidate_urls])
        validation_entries = annotate_source_validation(
            [
                {
                    "source_type": "rss",
                    "label": row.get("url"),
                    "url": row.get("url"),
                    "ok": row.get("ok", False),
                    "article_count": row.get("article_count", 0),
                    "feed_title": row.get("feed_title"),
                    "sample_titles": row.get("sample_titles", []),
                    "error": row.get("error"),
                }
                for row in tested
            ]
        )

    review = review_source_candidates(validation_entries, min_non_risky=2)
    return {
        "source": source_snapshot,
        "topic": topic,
        "summary": review["summary"] if validation_entries else "No validated alternative feeds are available yet.",
        "alternatives": review["selected"],
        "discarded_alternatives": review["dropped"],
    }


@api_router.delete("/boards/{slug}/sources/{source_id}")
async def delete_board_source_endpoint(
    slug: str,
    source_id: int,
    session: AsyncSession = Depends(get_session),
):
    board = await _resolve_board(session, slug)
    if not _board_supports_rss_sources(board):
        raise HTTPException(status_code=400, detail="P0 source management only supports RSS sources.")
    ok = await db_service.delete_board_source(session, board, source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Source not found.")
    return {"status": "ok"}


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
    Generate a deep, structured weekly consolidation from recent summaries.
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
    max_days: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Lightweight check: how many unread articles and missing summaries exist."""
    board_obj = await _resolve_board(session, board)
    board_id = board_obj.id if board_obj else None
    # Use board's catchup_days as default window; explicit 0 means disabled.
    board_catchup = _board_catchup_days(board_obj)
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

    today_str = datetime.now().strftime("%Y-%m-%d")
    gaps = await db_service.get_gap_dates(session, days=safe_days, board_id=board_id)

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

    # Step 3: Collect unread articles only, then dedupe by URL and event cluster.
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
        entry["top_news"].append({
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
        })

    for date_value, entry in summaries_by_date.items():
        full = await db_service.get_summary_by_date(session, date_value, board_id=board_id)
        if full:
            entry["overview"] = full.overview
            entry["source_stats"] = full.source_stats or {}

    all_dates = sorted(summaries_by_date.keys())
    summaries_data = [summaries_by_date[d] for d in all_dates]

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

    # Step 5: Mark only the unread articles covered by this digest as read.
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


@api_router.get("/cache")
async def get_cache_overview(
    limit: int = 14,
    board: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """All stored summaries with viewed status for cache viewer."""
    safe_limit = max(1, min(limit, 30))
    board_obj = await _resolve_board(session, board) if board else None
    board_id = board_obj.id if board_obj else None
    return await db_service.get_cache_overview(session, limit=safe_limit, board_id=board_id)
