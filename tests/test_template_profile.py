from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.schemas import BoardCreateRequest
from app.services.llm.summary import (
    _get_editor_prompt,
    render_template_profile_instructions,
)
from app.models.schemas import ContentItem
from app.services.template_matching_service import (
    apply_template_match_filter,
    maybe_build_builtin_clarification,
    score_source_relevance,
)


def test_board_schema_rejects_non_object_template_profile():
    with pytest.raises(ValidationError):
        BoardCreateRequest(
            slug="bad-template",
            name="Bad Template",
            template_profile=["not", "an", "object"],
        )


def test_render_template_profile_instructions_uses_known_fields():
    rendered = render_template_profile_instructions(
        {
            "goal": "筛出有用技术动态",
            "selection_rules": ["官方优先", "排除营销稿"],
            "output_requirements": ["中文", "给出建议动作"],
        }
    )

    assert "结构化需求处理模板" in rendered
    assert "需求目标: 筛出有用技术动态" in rendered
    assert "筛选规则: 官方优先；排除营销稿" in rendered
    assert "输出要求: 中文；给出建议动作" in rendered


def test_editor_prompt_includes_template_profile_and_system_prompt():
    board = SimpleNamespace(
        name="AI",
        description="",
        output_language="zh",
        prompt_key="daily_briefing",
        system_prompt="每条最后加一句影响判断。",
        template_profile={
            "goal": "筛出影响 API 使用的 AI 动态",
            "content_focus": ["模型发布", "价格变化"],
        },
    )

    prompt = _get_editor_prompt(board, custom_instructions=board.system_prompt)

    assert "结构化需求处理模板" in prompt
    assert "筛出影响 API 使用的 AI 动态" in prompt
    assert "模型发布；价格变化" in prompt
    assert "每条最后加一句影响判断。" in prompt


def test_builtin_project_tools_clarification_uses_options():
    clarification = maybe_build_builtin_clarification([{"role": "user", "content": "热门项目与工具"}])

    assert clarification
    assert "热门项目与工具" in clarification["question"]
    assert clarification["allow_custom"] is True
    assert [option["id"] for option in clarification["options"]] == [
        "github_trending",
        "community_discussed",
        "mixed_project_tools",
    ]


def test_project_tool_source_relevance_drops_github_blog_policy_samples():
    profile = {
        "goal": "发现热门项目与工具",
        "selection_rules": ["优先具体开源项目、库、框架、CLI、SDK", "排除政策倡议、安全数据库、平台公告、公司声明"],
    }
    github_blog = {
        "source_type": "rss",
        "ok": True,
        "url": "https://github.blog/feed/",
        "feed_title": "GitHub Blog",
        "sample_titles": [
            "GitHub 安全数据库：漏洞数量破纪录，社区如何应对",
            "GitHub 加入联盟，呼吁修改加州 AI 透明度法案以保护开源",
        ],
    }
    repo_source = {
        "source_type": "github",
        "ok": True,
        "label": "astral-sh/uv",
        "sample_titles": ["astral-sh/uv released 0.5.0", "A fast Python package manager gains 20k stars"],
    }

    blog_score = score_source_relevance(github_blog, profile)
    repo_score = score_source_relevance(repo_source, profile)

    assert blog_score["template_relevant"] is False
    assert blog_score["relevance_label"] in {"low", "mismatch"}
    assert repo_score["template_relevant"] is True
    assert repo_score["relevance_score"] > blog_score["relevance_score"]


def test_template_match_filter_keeps_project_tools_and_filters_policy_news():
    profile = {
        "goal": "发现热门项目与工具",
        "selection_rules": ["优先具体开源项目、库、框架、CLI、SDK", "排除政策倡议、安全数据库、平台公告、公司声明"],
    }
    items = [
        ContentItem(
            id="1",
            source_type="github",
            title="astral-sh/uv released a new CLI for Python packaging",
            url="https://github.com/astral-sh/uv/releases/tag/1",
            content="Open source project release with SDK and CLI improvements.",
            source_name="astral-sh/uv",
        ),
        ContentItem(
            id="2",
            source_type="rss",
            title="GitHub joins alliance to change California AI transparency law",
            url="https://github.blog/policy",
            content="Company policy advocacy and open source governance.",
            source_name="GitHub Blog",
        ),
    ]

    kept, report = apply_template_match_filter(items, profile)

    assert [item.id for item in kept] == ["1"]
    assert report["candidate_count"] == 2
    assert report["kept_count"] == 1
    assert report["filtered_count"] == 1
    assert report["low_match_examples"][0]["title"].startswith("GitHub joins alliance")
