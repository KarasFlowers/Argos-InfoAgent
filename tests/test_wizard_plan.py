"""Unit tests for wizard pipeline stage ① (wizard_plan_sources / _normalize_plan)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.wizard import WizardMixin


def _norm(parsed):
    return WizardMixin._normalize_plan(parsed)


class TestNormalizePlan:
    def test_fills_defaults_for_empty(self):
        p = _norm({})
        assert p["ready"] is False
        assert p["source_type"] == "rss"   # safe default
        assert p["icon"] == "📌"
        assert p["search_terms"] == []
        assert p["candidates"]["hackernews"] is False

    def test_invalid_source_type_falls_back_to_rss(self):
        assert _norm({"source_type": "twitter"})["source_type"] == "rss"

    def test_keeps_valid_source_type(self):
        assert _norm({"source_type": "reddit"})["source_type"] == "reddit"

    def test_filters_malformed_rsshub_candidates(self):
        p = _norm({
            "candidates": {
                "rsshub": [
                    {"platform": "jike_user", "id": "ABC"},   # valid
                    {"id": "no-platform"},                      # dropped: no platform
                    "not-a-dict",                               # dropped: not a dict
                ],
            }
        })
        assert p["candidates"]["rsshub"] == [{"platform": "jike_user", "id": "ABC"}]

    def test_legacy_subreddit_candidates_are_dropped(self):
        # Reddit/GitHub now go through search_terms, not LLM-guessed candidates.
        p = _norm({"candidates": {"subreddits": ["LocalLLaMA"], "github_repos": [{"owner": "o", "repo": "r"}]}})
        assert "subreddits" not in p["candidates"]
        assert "github_repos" not in p["candidates"]
        assert p["candidates"]["rsshub"] == []

    def test_caps_search_terms_to_four(self):
        p = _norm({"search_terms": ["a", "b", "c", "d", "e", "f"]})
        assert len(p["search_terms"]) == 4


class TestWizardPlanSources:
    @pytest.mark.anyio
    async def test_parses_llm_json(self):
        mixin = WizardMixin()
        mixin.llm = MagicMock()
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = (
            '{"ready": true, "source_type": "reddit", "slug": "ml", '
            '"name": "机器学习", "search_terms": ["machine learning"]}'
        )
        mixin.llm.chat = AsyncMock(return_value=resp)

        with patch("app.services.llm.wizard.settings") as s:
            s.effective_llm_api_key = "sk-test"
            plan = await mixin.wizard_plan_sources([{"role": "user", "content": "ML subreddit"}])

        assert plan["ready"] is True
        assert plan["source_type"] == "reddit"
        # Reddit now flows through search_terms (real platform search), not LLM guesses.
        assert plan["search_terms"] == ["machine learning"]

    @pytest.mark.anyio
    async def test_no_api_key_returns_not_ready(self):
        mixin = WizardMixin()
        with patch("app.services.llm.wizard.settings") as s:
            s.effective_llm_api_key = None
            plan = await mixin.wizard_plan_sources([{"role": "user", "content": "hi"}])
        assert plan["ready"] is False

    @pytest.mark.anyio
    async def test_llm_failure_degrades_gracefully(self):
        mixin = WizardMixin()
        mixin.llm = MagicMock()
        mixin.llm.chat = AsyncMock(side_effect=Exception("boom"))
        with patch("app.services.llm.wizard.settings") as s:
            s.effective_llm_api_key = "sk-test"
            plan = await mixin.wizard_plan_sources([{"role": "user", "content": "hi"}])
        assert plan["ready"] is False
        assert "出错" in plan["clarify"]
