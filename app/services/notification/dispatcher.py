"""
Unified notification dispatcher.

Routes a ``DailySummaryResponse`` to explicitly configured notification channels.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


def _parse_channels(value: str) -> list[str]:
    return [channel.strip().lower() for channel in value.split(",") if channel.strip()]


class NotificationDispatcher:
    """Send notifications through configured channels."""

    async def send(
        self,
        summary: DailySummaryResponse,
        channels: list[str] | None = None,
    ) -> dict[str, bool]:
        """Dispatch summary through enabled channels.

        Args:
            summary: The daily summary to push.
            channels: Explicit channels for this send. When ``None``, uses
                the global ``NOTIFY_CHANNELS`` setting.

        Returns:
            Dict mapping channel name -> success boolean.
        """
        enabled_channels = _parse_channels(settings.NOTIFY_CHANNELS) if channels is None else channels
        enabled_channels = [channel.strip().lower() for channel in enabled_channels if channel.strip()]
        if not enabled_channels:
            logger.info("Notification skipped: no channels configured")
            return {}

        results: dict[str, bool] = {}

        unsupported = sorted(set(enabled_channels) - {"email"})
        for channel in unsupported:
            logger.warning("Notification channel '%s' is not supported", channel)
            results[channel] = False

        if "email" not in enabled_channels:
            return results

        try:
            from app.services.email_service import email_service

            ok = await email_service.send_daily_summary(summary)
            logger.info("Email notification %s", "sent" if ok else "failed")
            results["email"] = ok
        except Exception as e:
            logger.error("Email notification raised unexpected error: %s", e)
            results["email"] = False
        return results
