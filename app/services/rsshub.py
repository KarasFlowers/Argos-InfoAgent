"""RSSHub route catalog — turn Chinese-platform identifiers into standard RSS URLs.

Many high-value Chinese sources (公众号, 知乎, B站, 即刻, 微博 ...) expose no
standard RSS. RSSHub (https://github.com/DIYgod/RSSHub) generates standard
RSS/Atom for them, which is transparent to our existing RSS scraper/validator —
an RSSHub URL is just another feed.

This module is pure data + pure functions (no network). The base URL is
configurable so a self-hosted instance can be swapped in via RSSHUB_BASE_URL.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Each route: platform key -> {path template, required param names, label, example}.
# Keep this curated and high-signal rather than mirroring all 5000+ RSSHub routes.
ROUTES: dict[str, dict] = {
    "zhihu_people": {
        "path": "/zhihu/people/activities/{id}",
        "params": ["id"],
        "label": "知乎用户动态",
        "example": "zhihu_people id=zhang-san",
    },
    "zhihu_zhuanlan": {
        "path": "/zhihu/zhuanlan/{id}",
        "params": ["id"],
        "label": "知乎专栏",
        "example": "zhihu_zhuanlan id=example-column",
    },
    "bilibili_user_video": {
        "path": "/bilibili/user/video/{uid}",
        "params": ["uid"],
        "label": "B站UP主投稿",
        "example": "bilibili_user_video uid=2267573",
    },
    "bilibili_user_dynamic": {
        "path": "/bilibili/user/dynamic/{uid}",
        "params": ["uid"],
        "label": "B站UP主动态",
        "example": "bilibili_user_dynamic uid=2267573",
    },
    "weibo_user": {
        "path": "/weibo/user/{uid}",
        "params": ["uid"],
        "label": "微博用户",
        "example": "weibo_user uid=1234567890",
    },
    "jike_user": {
        "path": "/jike/user/{id}",
        "params": ["id"],
        "label": "即刻用户动态",
        "example": "jike_user id=ABCD1234",
    },
    "douban_people_status": {
        "path": "/douban/people/{id}/status",
        "params": ["id"],
        "label": "豆瓣用户广播",
        "example": "douban_people_status id=example",
    },
    "wechat_mp": {
        "path": "/wechat/mp/msgalbum/{biz}",
        "params": ["biz"],
        "label": "微信公众号合集",
        "example": "wechat_mp biz=Mzxxxxx",
    },
    "xiaohongshu_user": {
        "path": "/xiaohongshu/user/{user_id}/notes",
        "params": ["user_id"],
        "label": "小红书用户笔记",
        "example": "xiaohongshu_user user_id=abc123",
    },
}

DEFAULT_BASE_URL = "https://rsshub.app"


def _base_url() -> str:
    """Resolve the configured RSSHub base URL (trailing slash stripped)."""
    from app.core.config import settings

    base = getattr(settings, "RSSHUB_BASE_URL", None) or DEFAULT_BASE_URL
    return base.rstrip("/")


def build_rsshub_url(platform: str, **params: str) -> str | None:
    """Build a full RSSHub feed URL for a known platform route.

    Returns ``None`` for an unknown platform or when a required parameter is
    missing/empty, so callers can simply skip ``None`` results.
    """
    route = ROUTES.get(platform)
    if not route:
        return None
    values: dict[str, str] = {}
    for name in route["params"]:
        val = params.get(name)
        if val is None or not str(val).strip():
            logger.debug("rsshub: missing param '%s' for platform '%s'", name, platform)
            return None
        values[name] = str(val).strip()
    return _base_url() + route["path"].format(**values)


def list_routes() -> list[dict]:
    """Return the catalog as a list for prompt injection / introspection.

    Each entry: {platform, label, params, example}. No URLs (base may vary).
    """
    return [
        {
            "platform": key,
            "label": route["label"],
            "params": list(route["params"]),
            "example": route["example"],
        }
        for key, route in ROUTES.items()
    ]
