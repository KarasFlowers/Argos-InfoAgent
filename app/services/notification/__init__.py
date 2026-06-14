"""
Notification sub-package.

Provides email notification for daily summaries.

Usage:
    from app.services.notification import notify_service
    await notify_service.send(summary)
"""

from app.services.notification.dispatcher import NotificationDispatcher

notify_service = NotificationDispatcher()

__all__ = ["NotificationDispatcher", "notify_service"]
