"""
test_schemas.py - Unit tests for Pydantic schemas.

Tests:
  - ContentItem construction and validation
  - RSSItem / RSSResponse conversion
  - Edge cases (empty fields, special characters)
"""

from app.models.schemas import ContentItem, RSSItem, RSSResponse

# ---------------------------------------------------------------------------
# ContentItem
# ---------------------------------------------------------------------------


class TestContentItem:
    def test_minimal_construction(self):
        item = ContentItem(
            id="rss:test:1",
            source_type="rss",
            title="Test Article",
            url="https://example.com/article",
        )
        assert item.content is None
        assert item.author is None
        assert item.published_at == ""
        assert item.source_name == ""
        assert item.metadata == {}

    def test_full_construction(self):
        item = ContentItem(
            id="hn:12345",
            source_type="hackernews",
            title="Show HN: My Project",
            url="https://example.com/project",
            content="Full article text here",
            author="user123",
            published_at="2025-06-15T10:30:00",
            source_name="Hacker News",
            metadata={"score": 150, "comments": 42},
        )
        assert item.metadata["score"] == 150
        assert item.author == "user123"

    def test_empty_published_at_normalized(self):
        """Empty published_at should be normalized to empty string."""
        item = ContentItem(
            id="test:1",
            source_type="rss",
            title="T",
            url="https://example.com",
            published_at="",
        )
        assert item.published_at == ""

    def test_special_characters_in_title(self):
        item = ContentItem(
            id="test:1",
            source_type="rss",
            title="C++ vs Rust: A <comprehensive> comparison & benchmark",
            url="https://example.com",
        )
        assert "<" in item.title
        assert "&" in item.title

    def test_unicode_content(self):
        item = ContentItem(
            id="test:1",
            source_type="rss",
            title="中文标题测试",
            url="https://example.com",
            content="这是一段中文内容",
        )
        assert "中文" in item.title


# ---------------------------------------------------------------------------
# RSSItem
# ---------------------------------------------------------------------------


class TestRSSItem:
    def test_construction(self):
        item = RSSItem(
            title="Article",
            link="https://example.com/1",
            summary="Summary text",
            published="2025-01-01",
            source="Feed Name",
        )
        assert item.title == "Article"
        assert item.link == "https://example.com/1"


# ---------------------------------------------------------------------------
# RSSResponse
# ---------------------------------------------------------------------------


class TestRSSResponse:
    def test_construction(self):
        resp = RSSResponse(
            source_url="https://example.com/feed",
            items=[
                RSSItem(
                    title="A1",
                    link="https://example.com/1",
                    summary="S1",
                    published="2025-01-01",
                    source="Feed",
                ),
            ],
        )
        assert len(resp.items) == 1
        assert resp.source_url == "https://example.com/feed"

    def test_empty_items(self):
        resp = RSSResponse(source_url="https://example.com/feed", items=[])
        assert len(resp.items) == 0
