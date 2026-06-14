"""
Unified notification dispatcher.

Routes a ``DailySummaryResponse`` to the configured notification channel (email).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Send notifications via email."""

    async def send(
        self,
        summary: "DailySummaryResponse",
        channels: list[str] | None = None,
    ) -> dict[str, bool]:
        """Dispatch summary via email.

        Args:
            summary: The daily summary to push.
            channels: Ignored (kept for backward compatibility).

        Returns:
            Dict mapping channel name -> success boolean.
        """
        try:
            from app.services.email_service import email_service
            ok = await email_service.send_daily_summary(summary)
            logger.info("Email notification %s", "sent" if ok else "failed")
            return {"email": ok}
        except Exception as e:
            logger.error("Email notification raised unexpected error: %s", e)
            return {"email": False}
