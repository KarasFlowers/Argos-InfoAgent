"""Tests for rule-based content quality filtering."""

from app.models.schemas import ContentItem
from app.services.filtering_service import (
    _check_blacklist,
    _check_low_quality_domain,
    _check_low_signal,
)


def _make_item(title="A good article about AI", url="https://example.com/article", content=None):
    return ContentItem(
        id="test:1",
        source_type="rss",
        title=title,
        url=url,
        content=content,
        source_name="TestSource",
    )


class TestBlacklistFilter:
    def test_keyword_match_in_title(self):
        class Rule:
            pattern = "spam"
            match_field = "title"
            is_regex = False

        item = _make_item(title="This is spam content")
        reason = _check_blacklist(item, [Rule()])
        assert reason is not None
        assert "blacklist(keyword)" in reason

    def test_keyword_no_match(self):
        class Rule:
            pattern = "spam"
            match_field = "title"
            is_regex = False

        item = _make_item(title="Clean article about AI")
        reason = _check_blacklist(item, [Rule()])
        assert reason is None

    def test_regex_match_in_title(self):
        class Rule:
            pattern = r"\d{3}%"
            match_field = "title"
            is_regex = True

        item = _make_item(title="Get 100% free stuff")
        reason = _check_blacklist(item, [Rule()])
        assert reason is not None
        assert "blacklist(regex)" in reason

    def test_url_field_match(self):
        class Rule:
            pattern = "clickbait.com"
            match_field = "url"
            is_regex = False

        item = _make_item(url="https://clickbait.com/article/123")
        reason = _check_blacklist(item, [Rule()])
        assert reason is not None

    def test_content_field_match(self):
        class Rule:
            pattern = "buy now"
            match_field = "content"
            is_regex = False

        item = _make_item(content="Click here to buy now for 50% off!")
        reason = _check_blacklist(item, [Rule()])
        assert reason is not None


class TestLowSignalFilter:
    def test_short_title_filtered(self):
        item = _make_item(title="Hi")
        reason = _check_low_signal(item)
        assert reason is not None
        assert "title_too_short" in reason

    def test_normal_title_passes(self):
        item = _make_item(title="Google releases new Gemini model for developers")
        reason = _check_low_signal(item)
        assert reason is None

    def test_marketing_pattern_filtered(self):
        item = _make_item(title="震惊！99%的人不知道这个AI秘密")
        reason = _check_low_signal(item)
        assert reason is not None
        assert "marketing_pattern" in reason

    def test_thin_content_filtered(self):
        item = _make_item(content="Short")
        reason = _check_low_signal(item)
        assert reason is not None
        assert "content_too_thin" in reason

    def test_no_content_passes(self):
        """Items with no content at all should not be flagged for thin content."""
        item = _make_item(content=None)
        reason = _check_low_signal(item)
        assert reason is None


class TestLowQualityDomainFilter:
    def test_no_domains_configured_passes(self):
        item = _make_item(url="https://anything.com/article")
        reason = _check_low_quality_domain(item)
        assert reason is None
