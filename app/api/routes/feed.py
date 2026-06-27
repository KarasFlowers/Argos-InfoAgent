import html as html_mod
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.core.config import settings
from app.core.db import get_session
from app.models.schemas import RSSResponse
from app.services.db_service import db_service
from app.services.email_service import email_service
from app.services.rss_service import fetch_all_feeds

router = APIRouter()


@router.get("/feed")
async def get_rss_feed(
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Export the last 7 daily summaries as a standard RSS 2.0 XML feed.
    """
    board_obj = await resolve_active_board(session, board)
    board_id = board_obj.id if board_obj else None
    board_slug = board_obj.slug if board_obj else "default"
    board_name = board_obj.name if board_obj else "Argos"
    history = await db_service.get_summary_history(session, limit=7, board_id=board_id)

    site_url = settings.PUBLIC_BASE_URL.rstrip("/")

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "  <channel>",
        f"    <title>{html_mod.escape(board_name)} Daily Briefing</title>",
        f"    <link>{site_url}</link>",
        "    <description>Your personalized daily technology and AI briefing.</description>",
        "    <language>zh-cn</language>",
    ]

    for history_item in history.archive_items:
        summary = await db_service.get_summary_by_date(session, history_item.date, board_id=board_id)
        if not summary:
            continue

        try:
            dt = datetime.strptime(summary.date, "%Y-%m-%d")
            dt = dt.replace(tzinfo=UTC)
            pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
        except ValueError:
            pub_date = ""

        html_content = email_service._render_html(summary)
        escaped_html = (
            html_content.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

        xml.append("    <item>")
        xml.append(f'      <title>{html_mod.escape(f"{board_name} 日报 - {summary.date}")}</title>')
        xml.append(f'      <link>{html_mod.escape(f"{site_url}/?date={summary.date}&board={board_slug}")}</link>')
        xml.append(
            f'      <guid isPermaLink="false">argos-{html_mod.escape(board_slug)}-{html_mod.escape(summary.date)}</guid>'
        )
        if pub_date:
            xml.append(f"      <pubDate>{pub_date}</pubDate>")
        xml.append(f"      <description>{escaped_html}</description>")
        xml.append("    </item>")

    xml.append("  </channel>")
    xml.append("</rss>")

    return Response(content="\n".join(xml), media_type="application/rss+xml")


@router.get("/feeds", response_model=list[RSSResponse])
async def manually_trigger_rss_fetch():
    """
    Manually fetch updates from all configured RSS feeds.
    """
    return await fetch_all_feeds(settings.RSS_FEEDS)
