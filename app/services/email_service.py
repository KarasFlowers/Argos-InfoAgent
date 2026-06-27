import asyncio
import html as html_mod
import logging
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from app.core.config import settings
from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self):
        self.is_configured = bool(
            settings.SMTP_HOST
            and settings.SMTP_USER
            and settings.SMTP_PASSWORD
            and settings.SMTP_FROM
            and settings.EMAIL_SUBSCRIBERS
        )
        if not self.is_configured:
            logger.info("Email service not fully configured (missing SMTP or subscribers). Push features disabled.")

    def _render_html(self, summary: DailySummaryResponse) -> str:
        """Render a very simple but clean HTML email for the daily summary."""
        items_html = ""
        for item in summary.top_news:
            tags = " ".join(html_mod.escape(t) for t in item.tags)
            points = "".join([f"<li>{html_mod.escape(pt)}</li>" for pt in item.key_points])
            safe_link = html_mod.escape(item.original_link, quote=True)
            safe_headline = html_mod.escape(item.headline)
            safe_category = html_mod.escape(item.category)
            safe_source = html_mod.escape(item.source)
            items_html += f"""
            <div style="margin-bottom: 24px; padding: 16px; background-color: #f9fafb; border-radius: 8px;">
                <h3 style="margin-top: 0; color: #111827; font-size: 18px;">
                    <a href="{safe_link}" style="color: #2563eb; text-decoration: none;">{safe_headline}</a>
                </h3>
                <div style="margin-bottom: 12px; font-size: 13px;">
                    <span style="display: inline-block; background: #e0e7ff; color: #3730a3; padding: 2px 8px; border-radius: 12px; margin-right: 8px;">{safe_category}</span>
                    <span style="color: #6b7280;">{tags} | 源: {safe_source}</span>
                </div>
                <ul style="color: #4b5563; margin: 0; padding-left: 20px; line-height: 1.5;">
                    {points}
                </ul>
            </div>
            """

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Argos 日报 - {summary.date}</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f3f4f6; padding: 20px; margin: 0;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
                <div style="background-color: #111827; color: #ffffff; padding: 24px; text-align: center;">
                    <h1 style="margin: 0; font-size: 24px; letter-spacing: -0.5px;">Argos</h1>
                    <p style="margin: 8px 0 0 0; color: #9ca3af; font-size: 14px;">每日科技简报 - {summary.date}</p>
                </div>

                <div style="padding: 24px;">
                    <div style="font-size: 16px; line-height: 1.6; color: #374151; margin-bottom: 32px; border-left: 4px solid #2563eb; padding-left: 16px;">
                        {html_mod.escape(summary.overview)}
                    </div>

                    <h2 style="font-size: 20px; color: #111827; margin-bottom: 20px; border-bottom: 2px solid #f3f4f6; padding-bottom: 8px;">今日焦点</h2>
                    {items_html}
                </div>

                <div style="background-color: #f9fafb; padding: 16px; text-align: center; color: #6b7280; font-size: 12px; border-top: 1px solid #e5e7eb;">
                    <p style="margin: 0;">此简报由 Argos AI 自动生成。</p>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    async def send_daily_summary(self, summary: DailySummaryResponse) -> bool:
        if not self.is_configured:
            return False

        html_content = self._render_html(summary)

        msg = EmailMessage()
        msg["Subject"] = f"[Argos] 每日简报 - {summary.date}"
        msg["From"] = settings.SMTP_FROM
        msg["To"] = ", ".join(settings.EMAIL_SUBSCRIBERS)
        msg["Message-ID"] = make_msgid()
        msg.set_content("请使用支持 HTML 的邮件客户端查看此内容。")
        msg.add_alternative(html_content, subtype="html")

        try:
            # We run the blocking smtplib code in a thread to not block the async event loop
            await asyncio.to_thread(self._send_email_sync, msg)
            logger.info("Successfully pushed daily summary to %d subscribers.", len(settings.EMAIL_SUBSCRIBERS))
            return True
        except Exception as e:
            logger.error("Failed to send daily summary email: %s", e)
            return False

    def _send_email_sync(self, msg: EmailMessage):
        if settings.SMTP_PORT in (465, 8465):
            # SSL
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            # TLS
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)


email_service = EmailService()
