"""
test_content_item.py - Unit tests for ContentItem model and RSS -> ContentItem conversion.
"""

from app.models.schemas import ContentItem, RSSItem, RSSResponse
from app.services.rss_service import rss_responses_to_content_items


def test_content_item_defaults():
    """ContentItem should construct with minimal required fields."""
    item = ContentItem(
        id="test:unit:1",
        source_type="rss",
        title="Hello",
        url="https://example.com",
        published_at="2025-01-01T00:00:00",
    )
    assert item.content is None
    assert item.metadata == {}
    assert item.source_name == ""


def test_rss_responses_to_content_items():
    """rss_responses_to_content_items should convert RSSResponse list to ContentItem list."""
    rss = RSSResponse(
        source_url="https://example.com/feed",
        items=[
            RSSItem(
                title="Article 1",
                link="https://example.com/1",
                summary="Summary text",
                published="2025-01-01T00:00:00",
                source="Example Feed",
            ),
            RSSItem(
                title="Article 2",
                link="https://example.com/2",
                summary="",
                published="",
                source="Example Feed",
            ),
        ],
    )

    items = rss_responses_to_content_items([rss])

    assert len(items) == 2
    assert all(isinstance(i, ContentItem) for i in items)
    assert items[0].source_type == "rss"
    assert items[0].title == "Article 1"
    assert items[0].id.startswith("rss:feed:")
    assert not items[1].content  # empty summary -> None or empty string


def test_rss_responses_empty_input():
    assert rss_responses_to_content_items([]) == []
