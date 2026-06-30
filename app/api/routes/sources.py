import asyncio
import logging
import ssl
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.core.db import get_session
from app.core.url_safety import get_public_url, validate_public_url
from app.models.domain import Source
from app.services.db_service import db_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Max bytes of homepage HTML to read during RSS autodiscovery — feed <link>
# tags live in <head>, so a small cap is enough and bounds slow/huge pages.
_AUTODISCOVERY_MAX_BYTES = 512 * 1024


class TestFeedRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)


async def check_single_feed_url(url: str, timeout: float = 15.0) -> dict:
    """
    Test a single RSS feed URL. Returns a dict with:
      {"url", "ok", "feed_title", "article_count", "sample_titles", "error"}
    Does NOT cache the result. Never raises; failures are returned as ok=False.
    """
    import feedparser
    import httpx

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
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await get_public_url(client, url, timeout=timeout)
            resp.raise_for_status()

        # Pass raw bytes to feedparser so it can detect encoding from XML
        # declaration; resp.text may mis-decode non-UTF-8 feeds.
        feed = feedparser.parse(resp.content)
        entries = feed.entries or []
        feed_title = feed.feed.get("title", "Unknown Feed")

        if not entries and hasattr(feed, "bozo_exception"):
            bozo_msg = str(feed.bozo_exception)[:120]
            return {"url": url, "ok": False, "error": f"Feed 解析失败: {bozo_msg}"}

        return {
            "url": url,
            "ok": True,
            "feed_title": feed_title,
            "article_count": len(entries),
            "sample_titles": [entry.get("title", "Untitled") for entry in entries[:5]],
        }
    except ValueError as error:
        return {"url": url, "ok": False, "error": f"安全预检失败: {str(error)[:160]}"}
    except httpx.HTTPStatusError as error:
        return {"url": url, "ok": False, "error": f"HTTP {error.response.status_code}"}
    except httpx.TimeoutException:
        return {"url": url, "ok": False, "error": f"请求超时 ({int(timeout)}s)"}
    except httpx.ConnectError:
        return {"url": url, "ok": False, "error": "连接失败，请检查URL是否正确"}
    except ssl.SSLError as error:
        return {"url": url, "ok": False, "error": f"SSL错误: {str(error)[:100]}"}
    except Exception as error:
        return {"url": url, "ok": False, "error": str(error)[:200]}


async def discover_feed_links(homepage: str, timeout: float = 8.0, limit: int = 4) -> list[str]:
    """Discover RSS/Atom feed URLs advertised by a homepage. Never raises."""
    import httpx

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
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await get_public_url(client, homepage, timeout=timeout)
            resp.raise_for_status()
        html_text = resp.content[:_AUTODISCOVERY_MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
    except Exception as error:
        logger.debug("autodiscovery fetch failed for %s: %s", homepage, error)
        return []

    return parse_feed_links(html_text, homepage, limit)


def parse_feed_links(html_text: str, base_url: str, limit: int = 4) -> list[str]:
    """Parse feed-autodiscovery <link> tags from HTML. Pure; never raises."""
    feed_types = {"application/rss+xml", "application/atom+xml"}
    found: list[str] = []
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        for link in soup.find_all("link"):
            rel = " ".join(link.get("rel") or []).lower()
            link_type = (link.get("type") or "").strip().lower()
            href = (link.get("href") or "").strip()
            if not href or "alternate" not in rel or link_type not in feed_types:
                continue
            absolute = urljoin(base_url, href)
            try:
                validate_public_url(absolute)
            except ValueError:
                continue
            if absolute not in found:
                found.append(absolute)
            if len(found) >= limit:
                break
    except Exception as error:
        logger.debug("feed-link parse failed for %s: %s", base_url, error)
    return found


@router.post("/sources/test")
async def test_source_feed(payload: TestFeedRequest):
    """
    Test a single RSS feed URL. Returns status, article count, and sample titles.
    Does NOT cache the result.
    """
    return await check_single_feed_url(payload.url)


@router.post("/sources/test_all")
async def test_all_feeds(
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Test all RSS feeds for a given board concurrently.
    Returns a list of results: [{url, ok, feed_title, article_count, error}, ...]
    """
    board_obj = await resolve_active_board(session, board)
    if not board_obj:
        raise HTTPException(status_code=404, detail="No board found.")

    feeds = await db_service.get_board_rss_feeds(session, board_obj)
    if not feeds:
        return []

    results = await asyncio.gather(*[check_single_feed_url(url, timeout=10.0) for url in feeds])
    return [{key: value for key, value in result.items() if key != "sample_titles"} for result in results]


@router.get("/sources/coverage")
async def get_source_coverage_endpoint(
    board: str | None = None,
    date: str | None = None,
    days: int = Query(default=3, ge=2, le=7),
    limit: int = Query(default=6, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
):
    """How different sources covered the same recent stories."""
    from app.services.source_insights_service import get_source_coverage_analysis

    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None
    return await get_source_coverage_analysis(
        session,
        board_id=board_id,
        date=date,
        days=days,
        limit=limit,
    )


@router.get("/sources/dashboard")
async def get_sources_dashboard(
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Lightweight source health dashboard with template-fit review."""
    from app.services.board_api_service import serialize_source
    from app.services.source_insights_service import (
        get_source_coverage_analysis,
        score_source_quality,
        summarize_source_risk,
    )
    from app.services.template_matching_service import build_source_template_health_report

    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None
    stmt = select(Source)
    if board_id is None:
        stmt = stmt.where(Source.board_id.is_(None))
    else:
        stmt = stmt.where(Source.board_id == board_id)
    stmt = stmt.order_by(Source.id)
    sources = list((await session.execute(stmt)).scalars().all())

    template_health = await build_source_template_health_report(
        session,
        board_id=board_id,
        template_profile=getattr(board_obj, "template_profile", None) if board_obj else None,
    )
    health_by_name = {item["source"]: item for item in template_health.get("sources", [])}

    enriched = []
    for source in sources:
        row = serialize_source(source)
        row.update(
            score_source_quality(
                url=row["url"],
                source_type=row["source_type"],
                credibility_override=row.get("credibility_override"),
                health_status=row.get("health_status"),
            )
        )
        source_key = source.name or source.url
        template_row = health_by_name.get(source.name) or health_by_name.get(source.url) or health_by_name.get(source_key)
        if template_row:
            row["template_match_rate"] = template_row.get("match_rate")
            row["template_avg_match_score"] = template_row.get("avg_match_score")
            row["template_adopted_count"] = template_row.get("adopted_count")
            row["template_low_match_examples"] = template_row.get("low_match_examples", [])
            if str(template_row.get("recommended_action", "")).startswith("建议"):
                row["template_recommended_action"] = template_row["recommended_action"]
        row.update(summarize_source_risk(row))
        if row.get("template_recommended_action"):
            row["recommended_action"] = row["template_recommended_action"]
            row["risk_summary"] = (
                f"近期进入摘要的内容与模板匹配率偏低"
                f"{'（' + str(round(row['template_match_rate'] * 100)) + '%）' if row.get('template_match_rate') is not None else ''}。"
            )
        enriched.append(row)

    total = len(enriched)
    healthy = sum(1 for item in enriched if item.get("health_status") == "healthy")
    high_trust = sum(1 for item in enriched if item.get("trust_label") == "high")
    watch = sum(1 for item in enriched if item.get("trust_label") == "watch")
    risky = sum(1 for item in enriched if item.get("trust_label") == "risky")
    degraded = sum(1 for item in enriched if item.get("health_status") == "degraded")
    unhealthy = sum(1 for item in enriched if item.get("health_status") == "unhealthy")
    at_risk = [
        item
        for item in enriched
        if item.get("trust_label") in {"watch", "risky"}
        or item.get("health_status") in {"degraded", "unhealthy"}
        or item.get("template_recommended_action")
    ]
    return {
        "summary": {
            "total_sources": total,
            "healthy_sources": healthy,
            "high_trust_sources": high_trust,
            "watch_sources": watch,
            "risky_sources": risky,
            "degraded_sources": degraded,
            "unhealthy_sources": unhealthy,
            "manual_override_sources": sum(1 for item in enriched if item.get("credibility_override")),
            "avg_success_rate": None,
            "avg_response_time_ms": None,
            "template_health_status": template_health.get("status"),
        },
        "sources": enriched,
        "at_risk_sources": at_risk[:6],
        "template_health": template_health,
        "health_timeline": [],
        "recent_movements": [],
        "coverage_preview": await get_source_coverage_analysis(session, board_id=board_id, days=3, limit=3),
        "window_days": 14,
    }
