"""Curated feed catalog — known-good RSS feeds keyed by topic.

A pure-data + pure-function module that mirrors ``app/services/rsshub.py``:
no network, no settings, no side effects. The board wizard's RSS discovery
pipeline calls :func:`catalog_candidate_urls` *before* any Tavily search or
path probing, so topic matches resolve with zero network cost and feed URLs
that are known to be real (unlike LLM-guessed URLs).

Feed URLs here are deliberately curated to a small, high-confidence set:
- Sources already declared "真实可用" in ``board_wizard.md`` (机器之心, 少数派,
  阮一峰, linux.do, HN, TechCrunch, The Verge) are reused verbatim.
- Remaining sources are widely-recognised, long-stable feeds.
- Every URL still goes through ``_test_single_feed`` validation at discovery
  time — a stale entry here is simply marked ``ok=False`` and dropped, never
  polluting a board config.

The matching strategy is intentionally a case-insensitive *substring* test
over the concatenated plan text (intent + name + search_terms). At this data
scale (~60 feeds across 8 topics) there is no need for a search index; the
plain scan is O(topics × keywords) per call and trivially debuggable.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Catalog data
# ---------------------------------------------------------------------------
#
# Each topic maps to:
#   - ``keywords``: lowercase match terms (mixed CN/EN). A topic matches when
#     ANY keyword is a substring of the normalised plan text.
#   - ``feeds``: RSS/Atom URLs. URLs shared across topics (e.g. HN's frontpage
#     is relevant to AI, programming, open source, …) appear in each topic —
#     the matcher dedupes, so a feed is only suggested once per discovery run.
#   - ``label``: human-readable name, for introspection / future UI use.

CATALOG: dict[str, dict] = {
    "ai_ml": {
        "label": "AI / 机器学习",
        "keywords": [
            "ai",
            "ml",
            "人工智能",
            "机器学习",
            "大模型",
            "llm",
            "深度学习",
            "neural",
            "gpt",
            "transformer",
            "chatgpt",
            "diffusion",
            "rag",
        ],
        "feeds": [
            "https://hnrss.org/frontpage",
            "https://www.jiqizhixin.com/rss",
            "https://techcrunch.com/category/artificial-intelligence/feed/",
            "https://openai.com/blog/rss.xml",
            "https://www.anthropic.com/news/rss.xml",
        ],
    },
    "programming": {
        "label": "编程 / 软件开发",
        "keywords": [
            "编程",
            "开发",
            "coding",
            "软件工程",
            "programming",
            "程序员",
            "代码",
            "算法",
            "developer",
            "software engineering",
        ],
        "feeds": [
            "https://hnrss.org/frontpage",
            "https://www.ruanyifeng.com/blog/atom.xml",
            "https://linux.do/top.rss",
            "https://dev.to/feed",
        ],
    },
    "frontend": {
        "label": "前端 / Web",
        "keywords": [
            "前端",
            "frontend",
            "web 开发",
            "css",
            "javascript",
            "typescript",
            "react",
            "vue",
            "angular",
            "html",
            "web 前端",
        ],
        "feeds": [
            "https://hnrss.org/frontpage",
            "https://www.smashingmagazine.com/feed/",
            "https://web.dev/feed.xml",
            "https://css-tricks.com/feed/",
        ],
    },
    "backend_infra": {
        "label": "后端 / 基础设施",
        "keywords": [
            "后端",
            "backend",
            "基础设施",
            "infra",
            "devops",
            "云",
            "cloud",
            "server",
            "kubernetes",
            "docker",
            "微服务",
            "microservice",
            "数据库",
        ],
        "feeds": [
            "https://hnrss.org/frontpage",
            "https://www.infoq.com/feed/",
            "https://highscalability.com/rss/",
        ],
    },
    "security": {
        "label": "网络安全",
        "keywords": [
            "安全",
            "security",
            "网络安全",
            "cve",
            "漏洞",
            "vulnerability",
            "cyber",
            "渗透",
            "penetration",
            "加密",
            "crypto",
            "zero-day",
        ],
        "feeds": [
            "https://feeds.feedburner.com/TheHackersNews",
            "https://www.schneier.com/feed/atom/",
            "https://hnrss.org/newest",
        ],
    },
    "open_source": {
        "label": "开源",
        "keywords": [
            "开源",
            "open source",
            "github",
            "foss",
            "自由软件",
            "linux",
            "gnu",
            "mozilla",
        ],
        "feeds": [
            "https://hnrss.org/frontpage",
            "https://www.linux.com/feed/",
            "https://github.blog/feed/",
        ],
    },
    "tech_general": {
        "label": "综合科技资讯",
        "keywords": [
            "科技",
            "tech",
            "technology",
            "资讯",
            "新闻",
            "综合",
            "互联网",
            "数码",
            "industry",
        ],
        "feeds": [
            "https://sspai.com/feed",
            "https://www.theverge.com/rss/index.xml",
            "https://techcrunch.com/feed/",
            "https://36kr.com/feed",
        ],
    },
    "mobile": {
        "label": "移动开发",
        "keywords": [
            "移动",
            "mobile",
            "ios",
            "android",
            "flutter",
            "swift",
            "kotlin",
            "app 开发",
            "react native",
            "iphone",
            "ipad",
        ],
        "feeds": [
            "https://hnrss.org/frontpage",
            "https://www.iOSDevWeekly.com/issues.rss",
            "https://www.androidauthority.com/feed/",
        ],
    },
}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _normalise_plan_text(plan: dict) -> str:
    """Build a single lowercase haystack from the plan's text fields.

    Reads ``intent``, ``name`` and ``search_terms`` — all guaranteed present
    (with safe defaults) by :meth:`WizardMixin._normalize_plan`. Missing keys
    are tolerated so the function never raises on a partial plan dict.
    """
    parts: list[str] = []
    for key in ("intent", "name"):
        val = plan.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    terms = plan.get("search_terms")
    if isinstance(terms, list):
        parts.extend(str(t) for t in terms if isinstance(t, str) and t.strip())
    return " ".join(parts).lower()


def catalog_candidate_urls(plan: dict) -> list[str]:
    """Return deduplicated feed URLs whose topic matches the plan.

    A topic matches when ANY of its ``keywords`` appears as a case-insensitive
    substring of the concatenated plan text. Pure: no network, no settings,
    never raises. Returns ``[]`` when nothing matches or the plan is empty.

    Example::

        >>> catalog_candidate_urls({"intent": "我想看 AI 和大模型动态"})
        ['https://hnrss.org/frontpage',
         'https://www.jiqizhixin.com/rss', ...]
    """
    if not isinstance(plan, dict):
        return []

    haystack = _normalise_plan_text(plan)
    if not haystack:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    matched_topics: list[str] = []
    for topic_key, topic in CATALOG.items():
        keywords = topic.get("keywords") or []
        if not any(kw and kw in haystack for kw in keywords):
            continue
        matched_topics.append(topic_key)
        for url in topic.get("feeds") or []:
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

    if matched_topics:
        logger.debug(
            "feed_catalog: matched topics %s → %d candidate feeds",
            matched_topics,
            len(urls),
        )
    return urls


def list_topics() -> list[dict]:
    """Return the catalog as a list for introspection / future UI use.

    Each entry: ``{key, label, keywords, feed_count}``. URLs are omitted so
    the result is compact (mirrors ``rsshub.list_routes``'s design).
    """
    return [
        {
            "key": key,
            "label": topic.get("label", key),
            "keywords": list(topic.get("keywords") or []),
            "feed_count": len(topic.get("feeds") or []),
        }
        for key, topic in CATALOG.items()
    ]


__all__ = ["CATALOG", "catalog_candidate_urls", "list_topics"]
