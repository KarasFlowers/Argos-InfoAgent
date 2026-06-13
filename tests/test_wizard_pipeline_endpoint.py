"""Endpoint tests for the multi-stage board wizard pipeline (/boards/wizard).

Mocks the LLM stages and source validators to assert control flow:
  - ambiguous input → clarify, ready=False, no config
  - clear input → verified config + source_validation (response shape unchanged)
  - flag off → legacy single-call path is used instead
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.anyio
async def test_pipeline_ambiguous_returns_clarify(client):
    plan = {"ready": False, "clarify": "你想看哪个方向的内容？"}
    with patch("app.api.router.settings") as s, \
         patch("app.api.router.llm_service") as svc:
        s.WIZARD_PIPELINE_ENABLED = True
        svc.wizard_plan_sources = AsyncMock(return_value=plan)
        resp = await client.post("/api/v1/boards/wizard", json={"messages": [{"role": "user", "content": "有趣的"}]})

    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is False
    assert data["config"] is None
    assert "方向" in data["reply"]


@pytest.mark.anyio
async def test_pipeline_clear_returns_verified_config(client):
    plan = {"ready": True, "source_type": "rss", "slug": "ai", "name": "AI", "icon": "🤖"}
    pool = {
        "source_type": "rss",
        "verified": [{"source_type": "rss", "url": "https://a.com/feed", "ok": True}],
        "source_quality_report": {
            "summary": "Kept 1 stronger verified source and filtered out 1 risky option.",
            "safe_count": 1,
            "selected_count": 1,
            "dropped_count": 1,
            "selected": [{"url": "https://a.com/feed", "trust_label": "high", "trust_score": 88}],
            "dropped": [{"url": "http://risky.com/feed", "trust_label": "risky", "trust_score": 20, "selection_reason": "Dropped because safer verified sources were already available."}],
        },
    }
    final = {"reply": "已配置好", "config": {
        "slug": "ai", "name": "AI", "icon": "🤖", "source_type": "rss",
        "source_config": {"feeds": ["https://a.com/feed"]}, "system_prompt": "总结 AI 资讯",
    }}
    validation = [{"source_type": "rss", "url": "https://a.com/feed", "ok": True,
                   "article_count": 5, "sample_titles": ["x"]}]

    with patch("app.api.router.settings") as s, \
         patch("app.api.router.llm_service") as svc, \
         patch("app.api.router.discover_and_verify", AsyncMock(return_value=pool)), \
         patch("app.api.router._validate_config_sources", AsyncMock(return_value=validation)):
        s.WIZARD_PIPELINE_ENABLED = True
        svc.wizard_plan_sources = AsyncMock(return_value=plan)
        svc.wizard_finalize = AsyncMock(return_value=final)
        resp = await client.post("/api/v1/boards/wizard", json={"messages": [{"role": "user", "content": "每天的 AI 新闻"}]})

    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["config"]["source_config"]["feeds"] == ["https://a.com/feed"]
    # Response shape unchanged: source_validation + derived feed_validation present.
    assert data["source_validation"][0]["url"] == "https://a.com/feed"
    assert "trust_score" in data["source_validation"][0]
    assert "trust_label" in data["source_validation"][0]
    assert "source_discovery_report" in data
    assert data["source_discovery_report"]["dropped_count"] == 1
    assert data["source_discovery_report"]["safe_count"] == 1
    assert data["feed_validation"][0]["url"] == "https://a.com/feed"


@pytest.mark.anyio
async def test_pipeline_finalize_no_config_not_ready(client):
    plan = {"ready": True, "source_type": "rss", "slug": "ai", "name": "AI", "icon": "🤖"}
    with patch("app.api.router.settings") as s, \
         patch("app.api.router.llm_service") as svc, \
         patch("app.api.router.discover_and_verify", AsyncMock(return_value={"verified": []})):
        s.WIZARD_PIPELINE_ENABLED = True
        svc.wizard_plan_sources = AsyncMock(return_value=plan)
        svc.wizard_finalize = AsyncMock(return_value={"reply": "源太少", "config": None})
        resp = await client.post("/api/v1/boards/wizard", json={"messages": [{"role": "user", "content": "x"}]})

    data = resp.json()
    assert data["ready"] is False
    assert data["config"] is None


@pytest.mark.anyio
async def test_flag_off_uses_legacy_path(client):
    legacy = {"reply": "legacy", "ready": False, "config": None}
    with patch("app.api.router.settings") as s, \
         patch("app.api.router.llm_service") as svc:
        s.WIZARD_PIPELINE_ENABLED = False
        svc.wizard_suggest_board = AsyncMock(return_value=legacy)
        svc.wizard_plan_sources = AsyncMock()  # must NOT be called
        resp = await client.post("/api/v1/boards/wizard", json={"messages": [{"role": "user", "content": "hi"}]})

    assert resp.status_code == 200
    assert resp.json()["reply"] == "legacy"
    svc.wizard_suggest_board.assert_awaited_once()
    svc.wizard_plan_sources.assert_not_called()


@pytest.mark.anyio
async def test_wizard_preview_returns_structured_quality_report(client):
    preview_sources = [
        {
            "source_type": "rss",
            "url": "https://safe.example/feed",
            "label": "Safe Feed",
            "ok": True,
            "article_count": 6,
            "sample_titles": ["One", "Two"],
        },
        {
            "source_type": "rss",
            "url": "http://risky.example/feed",
            "label": "Risky Feed",
            "ok": True,
            "article_count": 2,
            "sample_titles": ["Three"],
        },
    ]
    review_report = {
        "summary": "Kept 1 stronger verified source and filtered out 1 risky option.",
        "safe_count": 1,
        "selected": [{"url": "https://safe.example/feed", "trust_label": "high", "trust_score": 88}],
        "dropped": [{"url": "http://risky.example/feed", "trust_label": "risky", "trust_score": 20}],
    }

    with patch("app.api.router._validate_config_sources", AsyncMock(return_value=preview_sources)), \
         patch("app.services.source_insights_service.annotate_source_validation", lambda items: items), \
         patch("app.services.source_insights_service.review_source_candidates", lambda items, min_non_risky=2: review_report):
        resp = await client.post("/api/v1/boards/wizard/preview", json={"config": {"source_type": "rss", "source_config": {"feeds": ["https://safe.example/feed"]}}})

    assert resp.status_code == 200
    data = resp.json()
    assert data["quality_report"]["safe_count"] == 1
    assert data["quality_report"]["selected"][0]["url"] == "https://safe.example/feed"
    assert data["quality_report"]["dropped"][0]["url"] == "http://risky.example/feed"


@pytest.mark.anyio
async def test_wizard_fix_feeds_filters_risky_replacements(client):
    async def fake_test_feed(url: str, timeout: float = 8.0):
        return {
            "url": url,
            "ok": True,
            "article_count": 5,
            "feed_title": url.rsplit("/", 1)[-1],
            "sample_titles": ["One", "Two", "Three"],
            "credibility_override": "risky" if "risky" in url else "",
        }

    with patch("app.api.router.llm_service") as svc, \
         patch("app.api.router._test_single_feed", side_effect=fake_test_feed):
        svc.suggest_alternative_feeds = AsyncMock(return_value=[
            {
                "original": "https://broken.example/feed",
                "suggestions": [
                    "https://safe-a.example/feed",
                    "https://safe-b.example/feed",
                    "https://risky.example/feed",
                ],
            }
        ])
        resp = await client.post(
            "/api/v1/boards/wizard/fix-feeds",
            json={"topic": "AI", "broken_urls": ["https://broken.example/feed"]},
        )

    assert resp.status_code == 200
    group = resp.json()["alternatives"][0]
    assert [item["url"] for item in group["suggestions"]] == [
        "https://safe-a.example/feed",
        "https://safe-b.example/feed",
    ]
    assert group["discarded_suggestions"][0]["url"] == "https://risky.example/feed"
    assert group["quality_report"]["safe_count"] == 2


# --- discover_and_verify source gating (regression: multi must not auto-add HN) ---

@pytest.mark.anyio
async def test_multi_without_hn_does_not_probe_hn():
    """A multi board that did not request Hacker News must not get HN attached.
    HN is a global single source that probes ok regardless of config, so the
    gating must come from the planner's signals, not the source_type alone.
    Reddit/GitHub gate on search_terms (real platform search)."""
    from app.api import router

    plan = {
        "source_type": "multi",
        "name": "x", "intent": "y",
        "search_terms": ["machine learning"],   # enables reddit/github search
        "homepage_hints": [],
        "candidates": {"hackernews": False, "rsshub": []},
    }
    probed = []

    async def fake_group(sub_st, cfg, timeout, deep):
        probed.append(sub_st)
        return [{"source_type": sub_st, "ok": True}]

    with patch("app.api.router._discover_rss_candidates", AsyncMock(return_value=[])), \
         patch("app.api.router._verify_and_fix_feeds", AsyncMock(return_value=[])), \
         patch("app.api.router._discover_reddit_config", AsyncMock(return_value={"subreddits": [{"subreddit": "ML"}]})), \
         patch("app.api.router._discover_github_config", AsyncMock(return_value={"repos": [{"owner": "o", "repo": "r"}]})), \
         patch("app.api.router._validate_source_group", side_effect=fake_group):
        pool = await router.discover_and_verify(plan)

    assert "hackernews" not in probed   # not requested → not probed
    assert "reddit" in probed           # search_terms present → reddit searched
    assert "github" in probed           # search_terms present → github searched


@pytest.mark.anyio
async def test_multi_with_hn_flag_probes_hn():
    from app.api import router

    plan = {
        "source_type": "multi", "name": "x", "intent": "y",
        "search_terms": [], "homepage_hints": [],
        "candidates": {"hackernews": True, "rsshub": []},
    }
    probed = []

    async def fake_group(sub_st, cfg, timeout, deep):
        probed.append(sub_st)
        return [{"source_type": sub_st, "ok": True}]

    with patch("app.api.router._discover_rss_candidates", AsyncMock(return_value=[])), \
         patch("app.api.router._verify_and_fix_feeds", AsyncMock(return_value=[])), \
         patch("app.api.router._validate_source_group", side_effect=fake_group):
        pool = await router.discover_and_verify(plan)

    assert probed == ["hackernews"]   # no search_terms → no reddit/github


@pytest.mark.anyio
async def test_reddit_board_uses_platform_search():
    """A reddit board must populate subreddits from real search, not LLM guesses."""
    from app.api import router

    plan = {"source_type": "reddit", "name": "ML", "intent": "y", "search_terms": ["machine learning"], "candidates": {}}
    reddit_cfg_seen = {}

    async def fake_group(sub_st, cfg, timeout, deep):
        reddit_cfg_seen.update(cfg)
        return [{"source_type": "reddit", "ok": True}]

    with patch("app.api.router._discover_reddit_config", AsyncMock(return_value={"subreddits": [{"subreddit": "MachineLearning"}], "fetch_comments": 5})), \
         patch("app.api.router._validate_source_group", side_effect=fake_group):
        pool = await router.discover_and_verify(plan)

    assert reddit_cfg_seen["subreddits"] == [{"subreddit": "MachineLearning"}]
    assert len(pool["verified"]) == 1
