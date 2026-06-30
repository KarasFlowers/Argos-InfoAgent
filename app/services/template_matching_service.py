"""Template demand matching helpers for wizard and summary quality control."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import DailySummary, NewsItem
from app.models.schemas import ContentItem


_TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_+#.-]{1,}|[\u4e00-\u9fff]{2,}")
_PROJECT_TOOL_POSITIVE = (
    "github",
    "repo",
    "repository",
    "open source",
    "project",
    "tool",
    "tools",
    "library",
    "framework",
    "cli",
    "sdk",
    "api",
    "release",
    "released",
    "launch",
    "launched",
    "build",
    "developer",
    "devtool",
    "stars",
    "trending",
    "开源",
    "项目",
    "工具",
    "仓库",
    "框架",
    "库",
    "命令行",
    "发布",
    "上线",
)
_PROJECT_TOOL_NEGATIVE = (
    "policy",
    "policies",
    "law",
    "act",
    "bill",
    "regulation",
    "regulatory",
    "transparency",
    "alliance",
    "coalition",
    "advocacy",
    "security database",
    "vulnerability database",
    "vulnerabilities",
    "governance",
    "company",
    "california",
    "政策",
    "法规",
    "法案",
    "透明度",
    "联盟",
    "倡议",
    "漏洞数据库",
    "安全数据库",
    "公司",
)
_GENERIC_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "what",
    "when",
    "where",
    "news",
    "latest",
    "today",
    "daily",
    "update",
    "updates",
    "内容",
    "信息",
    "最新",
    "热门",
    "每日",
    "关注",
}


@dataclass
class TemplateMatchResult:
    match_score: float
    match_reason: str
    mismatch_reason: str
    should_include: bool

    def as_dict(self) -> dict:
        return {
            "match_score": self.match_score,
            "match_reason": self.match_reason,
            "mismatch_reason": self.mismatch_reason,
            "should_include": self.should_include,
        }


def normalize_clarification(value) -> dict | None:
    """Coerce an LLM clarification block into the public wizard shape."""
    if not isinstance(value, dict):
        return None
    question = str(value.get("question") or "").strip()
    raw_options = value.get("options")
    if not question or not isinstance(raw_options, list):
        return None
    options = []
    for idx, raw in enumerate(raw_options[:6]):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("value") or "").strip()
        if not label:
            continue
        option_id = str(raw.get("id") or f"option_{idx + 1}").strip()
        option = {
            "id": option_id,
            "label": label,
            "value": str(raw.get("value") or label).strip(),
        }
        description = str(raw.get("description") or "").strip()
        if description:
            option["description"] = description
        options.append(option)
    if not options:
        return None
    return {"question": question, "options": options, "allow_custom": bool(value.get("allow_custom", True))}


def maybe_build_builtin_clarification(messages: list[dict]) -> dict | None:
    """Deterministic first-turn clarification for broad project/tool requests."""
    user_messages = [str(m.get("content", "")) for m in messages if m.get("role") == "user"]
    if len(user_messages) != 1:
        return None
    text = user_messages[-1].strip().lower()
    if not text:
        return None
    wants_project_tools = (
        ("热门" in text and ("项目" in text or "工具" in text))
        or ("trending" in text and ("project" in text or "tool" in text))
        or ("popular" in text and ("project" in text or "tool" in text))
    )
    if not wants_project_tools:
        return None
    return {
        "question": "你说的“热门项目与工具”更想按什么标准筛选？",
        "options": [
            {
                "id": "github_trending",
                "label": "GitHub 高星项目",
                "description": "优先看近期高星、增长快、release 活跃的开源项目。",
                "value": "我想看 GitHub 上近期高星或增长快的开源项目、库、框架、CLI 和 SDK，排除 GitHub 平台政策、安全数据库、公司公告。",
            },
            {
                "id": "community_discussed",
                "label": "社区热议工具",
                "description": "优先看 Hacker News、Reddit 等开发者社区讨论热的工具。",
                "value": "我想看 HN/Reddit 等开发者社区正在热议的新项目与工具，关注讨论热度和实际使用价值，排除政策新闻和平台公告。",
            },
            {
                "id": "mixed_project_tools",
                "label": "混合推荐",
                "description": "同时参考 GitHub、HN/Reddit 和技术源，偏实用发现。",
                "value": "我想混合关注 GitHub 热门开源项目、HN/Reddit 热议工具和实用开发者工具发布，优先具体项目与工具，排除公司新闻、法规政策和安全数据库。",
            },
        ],
        "allow_custom": True,
    }


def is_project_tool_profile(template_profile: dict | None, extra_text: str = "") -> bool:
    text = _profile_text(template_profile, extra_text).lower()
    if not text:
        return False
    return (
        ("热门" in text and ("项目" in text or "工具" in text))
        or ("project" in text and "tool" in text)
        or ("github" in text and ("repo" in text or "repository" in text))
        or ("开源" in text and ("项目" in text or "工具" in text))
    )


def score_source_relevance(entry: dict, template_profile: dict | None, extra_text: str = "") -> dict:
    if not isinstance(template_profile, dict) or not template_profile:
        return {
            "relevance_score": 50.0,
            "relevance_label": "unknown",
            "relevance_reason": "未配置结构化模板，跳过需求相关性审查。",
            "relevance_mismatch_reason": "",
            "template_relevant": True,
        }
    samples = " ".join(str(title) for title in (entry.get("sample_titles") or []) if title)
    label = str(entry.get("feed_title") or entry.get("label") or entry.get("url") or entry.get("source_type") or "")
    text = f"{label} {samples}"
    result = score_text_against_template(text, template_profile, extra_text=extra_text, source_type=entry.get("source_type"))
    if not entry.get("ok"):
        result.should_include = False
        if not result.mismatch_reason:
            result.mismatch_reason = "来源不可用。"
    return {
        "relevance_score": result.match_score,
        "relevance_label": _score_label(result.match_score),
        "relevance_reason": result.match_reason if result.should_include else (result.mismatch_reason or result.match_reason),
        "relevance_mismatch_reason": result.mismatch_reason,
        "template_relevant": result.should_include,
    }


def annotate_source_relevance(entries: list[dict], template_profile: dict | None, extra_text: str = "") -> list[dict]:
    out = []
    for entry in entries or []:
        merged = dict(entry)
        merged.update(score_source_relevance(merged, template_profile, extra_text=extra_text))
        out.append(merged)
    return out


def score_content_item(item: ContentItem, template_profile: dict | None, extra_text: str = "") -> TemplateMatchResult:
    text = f"{item.title} {item.content or ''} {item.source_name or ''} {item.source_type or ''}"
    return score_text_against_template(text, template_profile, extra_text=extra_text, source_type=item.source_type)


def apply_template_match_filter(
    items: list[ContentItem],
    template_profile: dict | None,
    *,
    extra_text: str = "",
    min_score: float = 42.0,
    fallback_keep: int = 6,
) -> tuple[list[ContentItem], dict]:
    """Filter fetched items by how well they satisfy the board template."""
    if not isinstance(template_profile, dict) or not template_profile:
        return items, {"enabled": False}

    scored: list[tuple[ContentItem, TemplateMatchResult]] = [
        (item, score_content_item(item, template_profile, extra_text=extra_text)) for item in items
    ]
    kept = [item for item, score in scored if score.should_include and score.match_score >= min_score]
    fallback_used = False
    if not kept and scored:
        fallback_used = True
        kept = [
            item
            for item, _score in sorted(scored, key=lambda pair: pair[1].match_score, reverse=True)[
                : max(1, min(fallback_keep, len(scored)))
            ]
        ]

    kept_object_ids = {id(item) for item in kept}
    dropped = [(item, score) for item, score in scored if id(item) not in kept_object_ids]
    report = {
        "enabled": True,
        "candidate_count": len(items),
        "kept_count": len(kept),
        "filtered_count": len(dropped),
        "fallback_used": fallback_used,
        "min_score": min_score,
        "low_match_examples": [
            {
                "title": item.title,
                "source": item.source_name or item.source_type,
                **score.as_dict(),
            }
            for item, score in sorted(dropped, key=lambda pair: pair[1].match_score)[:5]
        ],
        "kept_examples": [
            {
                "title": item.title,
                "source": item.source_name or item.source_type,
                **score.as_dict(),
            }
            for item, score in sorted(
                [(item, score) for item, score in scored if id(item) in kept_object_ids],
                key=lambda pair: pair[1].match_score,
                reverse=True,
            )[:5]
        ],
    }
    return kept, report


def score_text_against_template(
    text: str,
    template_profile: dict | None,
    *,
    extra_text: str = "",
    source_type: str | None = None,
) -> TemplateMatchResult:
    profile_text = _profile_text(template_profile, extra_text)
    text_l = (text or "").lower()
    profile_l = profile_text.lower()
    score = 50.0
    reasons: list[str] = []
    mismatches: list[str] = []

    required_tokens = _profile_tokens(template_profile, extra_text=extra_text)
    text_tokens = _tokens(text)
    if required_tokens:
        overlap = required_tokens & text_tokens
        if overlap:
            score += min(20.0, len(overlap) * 4.0)
            reasons.append("匹配模板关键词：" + "、".join(sorted(overlap)[:4]))
        else:
            score -= 10.0
            mismatches.append("未命中模板关键词")

    if is_project_tool_profile(template_profile, extra_text):
        positive_hits = [word for word in _PROJECT_TOOL_POSITIVE if word in text_l]
        negative_hits = [word for word in _PROJECT_TOOL_NEGATIVE if word in text_l]
        host = _host(text_l)
        if source_type in {"github", "hackernews", "reddit"}:
            score += 12
            reasons.append("来源类型适合发现项目/工具")
        if positive_hits:
            score += min(28.0, len(set(positive_hits)) * 6.0)
            reasons.append("包含项目/工具信号：" + "、".join(sorted(set(positive_hits))[:4]))
        else:
            score -= 18.0
            mismatches.append("不像具体项目或工具")
        if negative_hits:
            score -= min(45.0, len(set(negative_hits)) * 14.0)
            mismatches.append("包含应排除主题：" + "、".join(sorted(set(negative_hits))[:4]))
        if "github.blog" in host or "github.blog" in text_l:
            score -= 16.0
            mismatches.append("GitHub Blog 更偏平台新闻，需样本强相关才保留")

    include_keywords, exclude_keywords = _selection_keywords(template_profile)
    include_hits = [kw for kw in include_keywords if kw.lower() in text_l]
    exclude_hits = [kw for kw in exclude_keywords if kw.lower() in text_l]
    if include_hits:
        score += min(18.0, len(include_hits) * 5.0)
        reasons.append("符合纳入规则：" + "、".join(include_hits[:3]))
    if exclude_hits:
        score -= min(36.0, len(exclude_hits) * 12.0)
        mismatches.append("触发排除规则：" + "、".join(exclude_hits[:3]))

    score = round(max(0.0, min(100.0, score)), 1)
    should_include = score >= 42.0 and not (score < 55.0 and len(mismatches) > len(reasons))
    if not reasons:
        reasons.append("与模板需求存在基础相关性" if should_include else "")
    return TemplateMatchResult(
        match_score=score,
        match_reason="；".join(r for r in reasons if r)[:240],
        mismatch_reason="；".join(mismatches)[:240],
        should_include=should_include,
    )


async def build_source_template_health_report(
    session: AsyncSession,
    *,
    board_id: int | None,
    template_profile: dict | None,
    days: int = 14,
) -> dict:
    """Summarize historical source fit using saved summaries."""
    if not isinstance(template_profile, dict) or not template_profile:
        return {"status": "insufficient_data", "summary": "该板块还没有结构化模板，暂不计算需求匹配率。", "sources": []}

    cutoff = (datetime.now() - timedelta(days=max(1, min(days, 60)))).strftime("%Y-%m-%d")
    stmt = (
        select(DailySummary.date, NewsItem)
        .join(NewsItem, NewsItem.summary_id == DailySummary.id)
        .where(DailySummary.date >= cutoff)
        .order_by(desc(DailySummary.date), desc(NewsItem.id))
    )
    if board_id is not None:
        stmt = stmt.where(DailySummary.board_id == board_id)
    rows = list((await session.execute(stmt)).all())
    if not rows:
        return {"status": "insufficient_data", "summary": "历史摘要数据不足，暂时无法评估来源匹配率。", "sources": []}

    per_source: dict[str, list[float]] = defaultdict(list)
    latest: dict[str, str] = {}
    examples: dict[str, list[dict]] = defaultdict(list)
    for date_value, item in rows:
        source = item.source or "未知来源"
        text = f"{item.headline} {' '.join(str(p) for p in (item.key_points or []))} {' '.join(str(t) for t in (item.tags or []))}"
        score = score_text_against_template(text, template_profile).match_score
        per_source[source].append(score)
        latest[source] = max(latest.get(source, ""), date_value)
        if score < 42 and len(examples[source]) < 3:
            examples[source].append({"headline": item.headline, "score": score})

    sources = []
    for source, scores in per_source.items():
        avg_score = round(sum(scores) / len(scores), 1)
        adopted_count = len(scores)
        low_count = sum(1 for score in scores if score < 42)
        match_rate = round((adopted_count - low_count) / adopted_count, 3) if adopted_count else None
        recommendation = "保持观察"
        if match_rate == 0 or (adopted_count >= 3 and match_rate is not None and match_rate < 0.5):
            recommendation = "建议降权或寻找替代来源"
        elif adopted_count >= 3 and avg_score >= 68:
            recommendation = "可继续保留"
        sources.append(
            {
                "source": source,
                "adopted_count": adopted_count,
                "avg_match_score": avg_score,
                "match_rate": match_rate,
                "latest_date": latest.get(source),
                "low_match_examples": examples[source],
                "recommended_action": recommendation,
            }
        )
    sources.sort(key=lambda item: (item["match_rate"] or 0, item["avg_match_score"]))
    weak_count = sum(1 for item in sources if item["recommended_action"].startswith("建议"))
    return {
        "status": "ok",
        "summary": f"最近 {days} 天评估 {len(sources)} 个历史来源，{weak_count} 个来源建议复查。",
        "sources": sources,
    }


def _profile_text(template_profile: dict | None, extra_text: str = "") -> str:
    if not isinstance(template_profile, dict):
        return extra_text or ""
    parts: list[str] = [extra_text or ""]
    for value in template_profile.values():
        parts.append(_value_text(value))
    return " ".join(part for part in parts if part)


def _value_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_value_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_value_text(child)}" for key, child in value.items())
    return str(value)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text or "") if token.lower() not in _GENERIC_STOPWORDS}


def _profile_tokens(template_profile: dict | None, *, extra_text: str = "") -> set[str]:
    if not isinstance(template_profile, dict):
        return _tokens(extra_text)
    values = []
    for key in ("goal", "content_focus", "source_preferences"):
        values.append(_value_text(template_profile.get(key)))
    values.append(extra_text)
    tokens = _tokens(" ".join(values))
    return {token for token in tokens if len(token) >= 3}


def _selection_keywords(template_profile: dict | None) -> tuple[list[str], list[str]]:
    if not isinstance(template_profile, dict):
        return [], []
    rules = template_profile.get("selection_rules") or []
    if isinstance(rules, str):
        rules = [rules]
    include: list[str] = []
    exclude: list[str] = []
    for raw in rules:
        text = str(raw).strip()
        if not text:
            continue
        lowered = text.lower()
        target = exclude if any(marker in lowered for marker in ("排除", "降低", "不要", "avoid", "exclude", "deprior")) else include
        target.extend(_extract_rule_terms(text))
    return include[:12], exclude[:12]


def _extract_rule_terms(text: str) -> list[str]:
    terms = []
    for token in _TOKEN_RE.findall(text):
        token = token.strip()
        if token and token.lower() not in _GENERIC_STOPWORDS and len(token) > 1:
            terms.append(token)
    return terms


def _host(text_or_url: str) -> str:
    try:
        parsed = urlsplit(text_or_url)
        return parsed.hostname or ""
    except Exception:
        return ""


def _score_label(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    if score >= 35:
        return "low"
    return "mismatch"
