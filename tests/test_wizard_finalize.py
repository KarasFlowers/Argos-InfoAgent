"""Unit tests for wizard pipeline stage ④ (wizard_finalize)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.wizard import WizardMixin


def _mixin_with_reply(content: str):
    mixin = WizardMixin()
    mixin.llm = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    mixin.llm.chat = AsyncMock(return_value=resp)
    return mixin


PLAN = {"intent": "AI 资讯", "slug": "ai-news", "name": "AI 资讯", "icon": "🤖", "source_type": "rss"}
POOL = {
    "source_type": "rss",
    "verified": [
        {"source_type": "rss", "label": "https://a.com/feed", "url": "https://a.com/feed",
         "ok": True, "sample_titles": ["标题1", "标题2"]},
    ],
}


class TestWizardFinalize:
    @pytest.mark.anyio
    async def test_builds_config_from_pool(self):
        mixin = _mixin_with_reply(
            '{"reply": "已为你选好源", "config": {"slug": "ai-news", "name": "AI 资讯", '
            '"icon": "🤖", "source_type": "rss", '
            '"source_config": {"feeds": ["https://a.com/feed"]}, '
            '"system_prompt": "用中文总结每日 AI 资讯"}}'
        )
        with patch("app.services.llm.wizard.settings") as s:
            s.effective_llm_api_key = "sk-test"
            out = await mixin.wizard_finalize(PLAN, POOL)

        assert out["config"]["source_config"]["feeds"] == ["https://a.com/feed"]
        assert out["config"]["system_prompt"]

        # The verified pool (with sample titles) must reach the LLM prompt.
        sent = mixin.llm.chat.call_args.kwargs["messages"][1]["content"]
        assert "https://a.com/feed" in sent
        assert "标题1" in sent

    @pytest.mark.anyio
    async def test_missing_slug_in_both_config_and_plan_invalidates(self):
        # slug/name absent from BOTH the LLM config and the plan → no valid config.
        # (When the plan has them, finalize intentionally falls back — see next test.)
        mixin = _mixin_with_reply(
            '{"reply": "x", "config": {"name": "", "slug": "", '
            '"source_type": "rss", "source_config": {}}}'
        )
        empty_plan = {"intent": "x", "slug": "", "name": "", "icon": "", "source_type": "rss"}
        with patch("app.services.llm.wizard.settings") as s:
            s.effective_llm_api_key = "sk-test"
            out = await mixin.wizard_finalize(empty_plan, POOL)
        assert out["config"] is None

    @pytest.mark.anyio
    async def test_falls_back_to_plan_slug_name_when_llm_omits(self):
        # Finalize's job is source selection + prompt; slug/name come from the plan.
        mixin = _mixin_with_reply(
            '{"reply": "x", "config": {"name": "", "slug": "", '
            '"source_type": "rss", "source_config": {"feeds": ["https://a.com/feed"]}, '
            '"system_prompt": "x"}}'
        )
        with patch("app.services.llm.wizard.settings") as s:
            s.effective_llm_api_key = "sk-test"
            out = await mixin.wizard_finalize(PLAN, POOL)
        assert out["config"]["slug"] == "ai-news"   # inherited from PLAN
        assert out["config"]["name"] == "AI 资讯"

    @pytest.mark.anyio
    async def test_invalid_source_type_falls_back_to_plan(self):
        mixin = _mixin_with_reply(
            '{"reply": "x", "config": {"slug": "ai-news", "name": "AI 资讯", '
            '"source_type": "bogus", "source_config": {}}}'
        )
        with patch("app.services.llm.wizard.settings") as s:
            s.effective_llm_api_key = "sk-test"
            out = await mixin.wizard_finalize(PLAN, POOL)
        assert out["config"]["source_type"] == "rss"  # from PLAN

    @pytest.mark.anyio
    async def test_llm_failure_returns_none_config(self):
        mixin = WizardMixin()
        mixin.llm = MagicMock()
        mixin.llm.chat = AsyncMock(side_effect=Exception("boom"))
        with patch("app.services.llm.wizard.settings") as s:
            s.effective_llm_api_key = "sk-test"
            out = await mixin.wizard_finalize(PLAN, POOL)
        assert out["config"] is None
        assert "出错" in out["reply"]

    @pytest.mark.anyio
    async def test_empty_pool_still_calls_llm(self):
        mixin = _mixin_with_reply(
            '{"reply": "源较少", "config": {"slug": "ai-news", "name": "AI 资讯", '
            '"source_type": "rss", "source_config": {"feeds": []}, "system_prompt": "x"}}'
        )
        with patch("app.services.llm.wizard.settings") as s:
            s.effective_llm_api_key = "sk-test"
            out = await mixin.wizard_finalize(PLAN, {"source_type": "rss", "verified": []})
        # Pool text must signal emptiness to the model.
        sent = mixin.llm.chat.call_args.kwargs["messages"][1]["content"]
        assert "候选池为空" in sent
        assert out["config"] is not None
