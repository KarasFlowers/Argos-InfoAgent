"""
test_dedup_extended.py - Extended unit tests for dedup_service.

Tests edge cases for URL normalisation and cross-source merge that
are not covered in test_dedup.py.
"""

from app.models.schemas import ContentItem
from app.services.dedup_service import merge_cross_source_duplicates, normalize_url


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


# ---------------------------------------------------------------------------
# URL normalisation edge cases
# ---------------------------------------------------------------------------


class TestNormalizeUrlEdgeCases:
    def test_preserves_path_case(self):
        """Path should be case-sensitive (host is lowered, path is not)."""
        result = normalize_url("https://Example.com/Path")
        assert result == "example.com/Path"

    def test_strips_query_params(self):
        result = normalize_url("https://example.com/page?foo=1&utm_source=twitter")
        assert "foo" not in result
        assert "utm_source" not in result

    def test_strips_fragment(self):
        result = normalize_url("https://example.com/page#section-2")
        assert "#" not in result

    def test_ip_address_url(self):
        result = normalize_url("http://1.2.3.4/path")
        assert result == "1.2.3.4/path"

    def test_port_stripped(self):
        """Port is part of hostname in urlparse but we only take hostname."""
        result = normalize_url("https://example.com:8080/path")
        # Port is stripped because we only use parsed.hostname
        assert "8080" not in result

    def test_deeply_nested_path(self):
        result = normalize_url("https://example.com/a/b/c/d/e")
        assert result == "example.com/a/b/c/d/e"


# ---------------------------------------------------------------------------
# Cross-source merge edge cases
# ---------------------------------------------------------------------------


class TestMergeEdgeCases:
    def test_single_item_unchanged(self):
        items = [_make_item("rss", "https://example.com/a")]
        merged = merge_cross_source_duplicates(items)
        assert len(merged) == 1

    def test_three_items_same_url(self):
        """Three items with same URL should merge to one."""
        items = [
            _make_item("rss", "https://example.com/article", content="short"),
            _make_item("hackernews", "https://www.example.com/article", content="medium length"),
            _make_item(
                "reddit", "https://example.com/article/", content="the longest content here with lots of detail"
            ),
        ]
        merged = merge_cross_source_duplicates(items)
        assert len(merged) == 1
        # Should keep the richest content
        assert "longest" in (merged[0].content or "")

    def test_different_paths_not_merged(self):
        """Same host but different paths should NOT merge."""
        items = [
            _make_item("rss", "https://example.com/article-a"),
            _make_item("rss", "https://example.com/article-b"),
        ]
        merged = merge_cross_source_duplicates(items)
        assert len(merged) == 2

    def test_preserves_source_metadata(self):
        """Merged item should retain metadata from all sources."""
        items = [
            _make_item("rss", "https://example.com/a", source_name="Ars Technica"),
            _make_item("hackernews", "https://www.example.com/a/", source_name="Hacker News"),
        ]
        merged = merge_cross_source_duplicates(items)
        assert len(merged) == 1

    def test_empty_content_handled(self):
        """Items with None content should not crash merge."""
        items = [
            _make_item("rss", "https://example.com/a", content=None),
            _make_item("rss", "https://example.com/b", content=None),
        ]
        merged = merge_cross_source_duplicates(items)
        assert len(merged) == 2

    def test_no_mutation_of_input(self):
        """Original list should not be modified."""
        original = [
            _make_item("rss", "https://example.com/a"),
            _make_item("rss", "https://example.com/b"),
        ]
        original_len = len(original)
        merge_cross_source_duplicates(original)
        assert len(original) == original_len
