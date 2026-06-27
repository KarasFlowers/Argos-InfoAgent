from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.services.notification import dispatcher
from app.services.notification.dispatcher import NotificationDispatcher


def test_notify_channels_default_is_empty():
    assert Settings().NOTIFY_CHANNELS == ""


@pytest.mark.anyio
async def test_notification_dispatcher_skips_when_no_channels_configured(monkeypatch):
    monkeypatch.setattr(dispatcher.settings, "NOTIFY_CHANNELS", "")
    service = NotificationDispatcher()

    result = await service.send(summary=object())

    assert result == {}


@pytest.mark.anyio
async def test_notification_dispatcher_sends_email_only_when_enabled(monkeypatch):
    fake_email_service = type("EmailService", (), {"send_daily_summary": AsyncMock(return_value=True)})()

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.services.email_service":
            return type("EmailModule", (), {"email_service": fake_email_service})
        return original_import(name, globals, locals, fromlist, level)

    original_import = __import__
    monkeypatch.setattr(dispatcher.settings, "NOTIFY_CHANNELS", "email")
    monkeypatch.setattr("builtins.__import__", fake_import)
    service = NotificationDispatcher()

    result = await service.send(summary=object())

    assert result == {"email": True}
    fake_email_service.send_daily_summary.assert_awaited_once()


@pytest.mark.anyio
async def test_notification_dispatcher_explicit_empty_channels_skip_global(monkeypatch):
    monkeypatch.setattr(dispatcher.settings, "NOTIFY_CHANNELS", "email")
    service = NotificationDispatcher()

    result = await service.send(summary=object(), channels=[])

    assert result == {}
