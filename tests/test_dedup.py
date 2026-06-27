"""
test_dedup.py - Unit tests for dedup_service (URL normalisation + cross-source merge).

AI semantic dedup is NOT tested here (requires LLM), only the deterministic helpers.
"""

import pytest

from app.models.schemas import ContentItem
from app.services.dedup_service import merge_cross_source_duplicates, normalize_url

# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://www.example.com/page/", "example.com/page"),
        ("https://www.example.com/page#section", "example.com/page"),
        ("https://www.example.com/page?utm_source=x&ref=y", "example.com/page"),
        ("https://example.com/page", "example.com/page"),
        ("http://WWW.EXAMPLE.COM/PATH/", "example.com/PATH"),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


# ---------------------------------------------------------------------------
# Cross-source merge
# ---------------------------------------------------------------------------


def _make_item(
    source_type: str,
    url: str,
    title: str = "T",
    content: str | None = None,
    source_name: str = "",
) -> ContentItem:
    return ContentItem(
        id=f"{source_type}:test:1",
        source_type=source_type,
        title=title,
        url=url,
        content=content,
        published_at="2025-01-01T00:00:00",
        source_name=source_name,
    )


def test_merge_removes_url_duplicates():
    """Two items pointing to the same URL should be merged into one."""
    a = _make_item("rss", "https://example.com/article", content="short")
    b = _make_item(
        "hackernews",
        "https://www.example.com/article/",
        content="longer body with HN comments\n--- Top Comments ---\nGreat!",
    )

    merged = merge_cross_source_duplicates([a, b])
    assert len(merged) == 1
    # Should keep the richer content
    assert "Top Comments" in (merged[0].content or "")


def test_merge_keeps_distinct_urls():
    """Items with different URLs should be kept."""
    a = _make_item("rss", "https://example.com/a")
    b = _make_item("rss", "https://example.com/b")

    merged = merge_cross_source_duplicates([a, b])
    assert len(merged) == 2


def test_merge_empty_input():
    assert merge_cross_source_duplicates([]) == []
