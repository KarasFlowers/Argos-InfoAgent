import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.api.routes.sources import check_single_feed_url, discover_feed_links
from app.api.schemas import BoardSourceDiscoverRequest, BoardWizardRequest
from app.core.config import settings
from app.core.db import get_session
from app.core.url_safety import get_public_url
from app.services.board_api_service import board_supports_rss_sources, build_source_topic, serialize_source
from app.services.db_service import db_service
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)
router = APIRouter()


async def _test_single_feed(url: str, timeout: float = 15.0) -> dict:
    return await check_single_feed_url(url, timeout=timeout)


async def _discover_feeds(homepage: str, timeout: float = 8.0, limit: int = 4) -> list[str]:
    return await discover_feed_links(homepage, timeout=timeout, limit=limit)


async def _resolve_board(session: AsyncSession, slug: str | None):
    return await resolve_active_board(session, slug)


def _serialize_source(source) -> dict:
    return serialize_source(source)


def _build_source_topic(board, source_name: str = "") -> str:
    return build_source_topic(board, source_name)


def _board_supports_rss_sources(board) -> bool:
    return board_supports_rss_sources(board)


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
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await get_public_url(client, url, timeout=timeout)
            resp.raise_for_status()
        return {"source_type": source_type, "label": label, "url": url, "ok": True}
    except ValueError as error:
        return {
            "source_type": source_type,
            "label": label,
            "url": url,
            "ok": False,
            "error": f"安全预检失败: {str(error)[:120]}",
        }
    except httpx.HTTPStatusError as e:
        return {
            "source_type": source_type,
            "label": label,
            "url": url,
            "ok": False,
            "error": f"HTTP {e.response.status_code}",
        }
    except httpx.TimeoutException:
        return {
            "source_type": source_type,
            "label": label,
            "url": url,
            "ok": False,
            "error": f"请求超时 ({int(timeout)}s)",
        }
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
    from datetime import timedelta

    from app.core.http_client import get_http_client

    client = get_http_client()
    since = datetime.now(UTC) - timedelta(hours=since_hours)
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
            "hackernews",
            "Hacker News",
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout,
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
                *[_enrich_deep(e, "github", sub_cfg) for e, (_, _, _, sub_cfg) in zip(entries, tasks, strict=False)]
            )
        return list(entries)

    if source_type == "pure_llm":
        return [
            {"source_type": "pure_llm", "label": "纯 LLM 生成", "ok": True, "article_count": 0, "sample_titles": []}
        ]

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
                *[_enrich_deep(e, "reddit", sub_cfg) for e, (_, _, _, sub_cfg) in zip(entries, tasks, strict=False)]
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
    for homepage, group in zip(homepages, discovered, strict=False):
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
    results = await asyncio.gather(*[_test_single_feed(root + path, timeout=6.0) for path in _COMMON_FEED_PATHS])
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
            len(verified),
            _DISCOVERY_RSS_TARGET,
            rounds,
        )
    return verified


@router.post("/boards/wizard")
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


@router.post("/boards/wizard/preview")
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


@router.post("/boards/wizard/fix-feeds")
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
        results = await asyncio.gather(*[_test_single_feed(u, timeout=8.0) for u in all_urls])
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
        group_entries = [validation_map[url] for url in group.get("suggestions", []) if url in validation_map]
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


@router.post("/boards/{slug}/sources/discover")
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
        "homepage_hints": [url for url in (plan.get("homepage_hints") or []) if isinstance(url, str) and url.strip()][
            :6
        ],
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


@router.get("/boards/{slug}/sources/{source_id}/alternatives")
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
