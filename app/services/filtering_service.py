"""Rule-based content quality filtering service.

Inserts between InterestFilter (personalization) and ScoringMixin (AI quality)
in the summary pipeline. Provides three layers of hard filtering:

1. Blacklist keywords (from DB) — exact or regex match on title/URL/content
2. Low-signal heuristics — title too short, marketing patterns, content too thin
3. Configurable low-quality domain list

Filtered items are saved to the FilteredItem table for admin review.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, UTC
from typing import Optional

from app.models.schemas import ContentItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default low-signal patterns (can be overridden via DB BlacklistKeyword table)
# ---------------------------------------------------------------------------

_DEFAULT_MARKETING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"震惊[!！]",
        r"必看[!！]",
        r"限时免费",
        r"赶紧[看买抢]",
        r"点击领取",
        r"震惊.*?真相",
        r"99%的人",
        r"你绝对",
        r"不看后悔",
        r"速来[!！]",
        r"大揭秘",
        r"最新消息.*?速看",
    ]
]

_MIN_TITLE_LENGTH = 10  # characters
_MIN_CONTENT_LENGTH = 80  # characters (RSS excerpt + full_text combined)

class FilteringResult:
    """Result of applying rule-based filters to a list of ContentItems."""

    def __init__(
        self,
        passed: list[ContentItem],
        filtered: list[tuple[ContentItem, str]],
    ) -> None:
        self.passed = passed
        self.filtered = filtered  # list of (item, reason)

    @property
    def filtered_count(self) -> int:
        return len(self.filtered)


async def apply_rule_filters(
    items: list[ContentItem],
    session=None,
    board_id: int | None = None,
) -> FilteringResult:
    """Apply all rule-based filters to a list of ContentItems.

    Pipeline order:
    1. Blacklist keyword filter (from DB if session provided)
    2. Low-signal heuristic filter
    3. Low-quality domain filter

    Returns a FilteringResult with passed items and filtered items with reasons.
    """
    blacklist_rules = []
    if session:
        try:
            from sqlalchemy import select
            from app.models.domain import BlacklistKeyword

            stmt = select(BlacklistKeyword).where(BlacklistKeyword.is_active == True)  # noqa: E712
            result = await session.execute(stmt)
            blacklist_rules = list(result.scalars().all())
        except Exception as err:
            logger.warning("Failed to load blacklist keywords: %s", err)

    passed: list[ContentItem] = []
    filtered: list[tuple[ContentItem, str]] = []

    for item in items:
        reason = _check_blacklist(item, blacklist_rules)
        if not reason:
            reason = _check_low_signal(item)

        if reason:
            filtered.append((item, reason))
        else:
            passed.append(item)

    # Persist filtered items for admin review
    if session and filtered:
        try:
            from app.models.domain import FilteredItem

            for item, reason in filtered:
                fi = FilteredItem(
                    title=item.title,
                    url=item.url,
                    source=item.source_name or item.source_type,
                    filter_reason=reason,
                    board_id=board_id,
                )
                session.add(fi)
            await session.flush()
        except Exception as err:
            logger.warning("Failed to save filtered items: %s", err)

    if filtered:
        logger.info(
            "Rule filter: %d/%d items filtered (%d passed)",
            len(filtered), len(items), len(passed),
        )

    return FilteringResult(passed=passed, filtered=filtered)


def _check_blacklist(item: ContentItem, rules: list) -> str | None:
    """Check item against blacklist keyword rules."""
    for rule in rules:
        field_value = ""
        if rule.match_field == "title":
            field_value = item.title
        elif rule.match_field == "url":
            field_value = item.url
        elif rule.match_field == "content":
            field_value = item.content or ""

        if not field_value:
            continue

        if rule.is_regex:
            try:
                if re.search(rule.pattern, field_value, re.IGNORECASE):
                    return f"blacklist(regex):{rule.pattern}"
            except re.error:
                continue
        else:
            if rule.pattern.lower() in field_value.lower():
                return f"blacklist(keyword):{rule.pattern}"

    return None


def _check_low_signal(item: ContentItem) -> str | None:
    """Check item against low-signal heuristic rules."""
    # Title too short
    if len(item.title.strip()) < _MIN_TITLE_LENGTH:
        return f"low_signal:title_too_short({len(item.title.strip())} chars)"

    # Marketing pattern in title
    for pattern in _DEFAULT_MARKETING_PATTERNS:
        if pattern.search(item.title):
            return f"low_signal:marketing_pattern"

    # Content too thin (RSS excerpt + full_text combined)
    content_length = len((item.content or "").strip())
    if content_length > 0 and content_length < _MIN_CONTENT_LENGTH:
        return f"low_signal:content_too_thin({content_length} chars)"

    return None


