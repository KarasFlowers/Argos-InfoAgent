"""Deterministic recommendation explanations for summary cards."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import DailySummaryResponse, SummaryItem
from app.services.db_service import db_service

PREFERENCE_CATEGORIES = ("focus_topic", "block_topic", "prefer_source", "avoid_source")


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def _signals(item: SummaryItem) -> set[str]:
    values = {_norm(item.category)}
    values.update(_norm(tag.lstrip("#")) for tag in item.tags or [])
    values.update(_norm(part) for part in (item.topic_path or "").replace("/", " ").split())
    return {value for value in values if value}


def _matching_values(candidates: list[str], signals: set[str]) -> list[str]:
    matches: list[str] = []
    for raw in candidates:
        value = _norm(raw)
        if not value:
            continue
        if value in signals or any(value in signal or signal in value for signal in signals):
            matches.append(raw)
    return matches


def _source_matches(candidates: list[str], source: str) -> list[str]:
    source_norm = _norm(source)
    matches: list[str] = []
    for raw in candidates:
        value = _norm(raw)
        if value and (value == source_norm or value in source_norm or source_norm in value):
            matches.append(raw)
    return matches


def build_assistant_questions(item: SummaryItem) -> list[str]:
    headline = (item.headline or "这条资讯").strip()
    category = (item.category or "").strip()
    tags = [str(tag).strip().lstrip("#") for tag in item.tags or [] if str(tag).strip()]
    topic = tags[0] if tags else category

    questions = [
        "这件事最值得关注的变化是什么？",
        f"{headline} 对开发者或产品有什么实际影响？",
    ]
    if topic:
        questions.append(f"把它放到 {topic} 的近期趋势里看，意味着什么？")
    else:
        questions.append("有哪些背景信息能帮助我更快理解它？")
    return questions[:3]


def explain_item(
    item: SummaryItem,
    preferences: dict[str, list[str]] | None = None,
    *,
    is_fallback: bool = False,
) -> SummaryItem:
    preferences = preferences or {category: [] for category in PREFERENCE_CATEGORIES}
    item_signals = _signals(item)
    matches: list[str] = []
    reasons: list[str] = []

    if is_fallback:
        item.preference_matches = []
        item.recommendation_reason = "AI 摘要暂时不可用，当前仅按原始来源展示"
        item.assistant_questions = build_assistant_questions(item)
        return item

    focus_matches = _matching_values(preferences.get("focus_topic", []), item_signals)
    if focus_matches:
        matches.extend([f"关注话题：{value}" for value in focus_matches[:2]])
        reasons.append(f"匹配你的关注话题：{'、'.join(focus_matches[:2])}")

    source_matches = _source_matches(preferences.get("prefer_source", []), item.source)
    if source_matches:
        matches.extend([f"优先来源：{value}" for value in source_matches[:2]])
        reasons.append(f"来自你优先关注的来源：{'、'.join(source_matches[:2])}")

    avoid_matches = _source_matches(preferences.get("avoid_source", []), item.source)
    if avoid_matches:
        matches.extend([f"降权来源：{value}" for value in avoid_matches[:2]])

    if not reasons and isinstance(item.persona_score, int | float) and item.persona_score > 0:
        reasons.append("与你近期的点赞和阅读偏好相近")

    if not reasons:
        tags = [str(tag).strip().lstrip("#") for tag in item.tags or [] if str(tag).strip()]
        if tags:
            reasons.append(f"围绕 {'、'.join(tags[:2])}，适合快速跟进")
        elif item.category:
            reasons.append(f"属于 {item.category} 方向的高价值更新")
        else:
            reasons.append("今日简报筛选出的重点资讯")

    if len(reasons) == 1:
        if item.source:
            reasons.append(f"来源：{item.source}")
        elif item.category:
            reasons.append(f"分类：{item.category}")

    item.preference_matches = matches[:4]
    item.recommendation_reason = "；".join(reasons[:2])
    item.assistant_questions = build_assistant_questions(item)
    return item


async def enrich_summary_explanations(
    summary: DailySummaryResponse | None,
    session: AsyncSession,
    board_id: int | None = None,
) -> DailySummaryResponse | None:
    if summary is None:
        return None

    try:
        preferences = await db_service.get_explicit_preferences(session, board_id=board_id)
    except Exception:
        preferences = {category: [] for category in PREFERENCE_CATEGORIES}

    is_fallback = bool(summary.recommendation_report.get("fallback"))
    summary.top_news = [explain_item(item, preferences, is_fallback=is_fallback) for item in summary.top_news]
    summary.catchup_news = [explain_item(item, preferences, is_fallback=is_fallback) for item in summary.catchup_news]
    return summary
