"""Tests for LLM output tolerance in Pydantic schemas."""

from app.models.schemas import DailySummaryResponse, SummaryItem


class TestSummaryItemTolerance:
    def test_title_to_headline_normalization(self):
        """LLM sometimes returns 'title' instead of 'headline'."""
        item = SummaryItem.model_validate(
            {
                "title": "AI breakthrough",
                "category": "tech",
                "key_points": ["point 1"],
                "original_link": "https://example.com",
                "source": "test",
            }
        )
        assert item.headline == "AI breakthrough"

    def test_key_points_string_to_list(self):
        """LLM sometimes returns key_points as a single string."""
        item = SummaryItem.model_validate(
            {
                "headline": "Test",
                "category": "tech",
                "key_points": "single point as string",
                "original_link": "https://example.com",
                "source": "test",
            }
        )
        assert isinstance(item.key_points, list)
        assert len(item.key_points) >= 1

    def test_missing_category_defaults_to_general(self):
        """Missing category should default to 'general'."""
        item = SummaryItem.model_validate(
            {
                "headline": "Test",
                "key_points": ["point"],
                "original_link": "https://example.com",
                "source": "test",
            }
        )
        assert item.category == "general"

    def test_missing_tags_defaults_to_empty_list(self):
        """Missing tags should default to empty list."""
        item = SummaryItem.model_validate(
            {
                "headline": "Test",
                "category": "tech",
                "key_points": ["point"],
                "original_link": "https://example.com",
                "source": "test",
            }
        )
        assert item.tags == []

    def test_normal_input_passes(self):
        """Standard well-formed input should work fine."""
        item = SummaryItem.model_validate(
            {
                "headline": "Normal headline",
                "category": "AI",
                "key_points": ["p1", "p2"],
                "tags": ["ai", "ml"],
                "original_link": "https://example.com",
                "source": "source",
            }
        )
        assert item.headline == "Normal headline"
        assert len(item.key_points) == 2
        assert len(item.tags) == 2


class TestDailySummaryResponseTolerance:
    def test_title_normalization_in_top_news(self):
        """top_news items with 'title' instead of 'headline' should be normalized."""
        data = {
            "date": "2024-01-01",
            "overview": "Test overview",
            "top_news": [
                {
                    "title": "Item 1",
                    "category": "tech",
                    "key_points": ["kp1"],
                    "original_link": "https://a.com",
                    "source": "s",
                },
            ],
        }
        resp = DailySummaryResponse.model_validate(data)
        assert resp.top_news[0].headline == "Item 1"

    def test_missing_date_gets_default(self):
        """Missing date should not crash."""
        data = {
            "overview": "Test",
            "top_news": [],
        }
        resp = DailySummaryResponse.model_validate(data)
        assert resp.date  # should have some default

    def test_empty_overview_ok(self):
        data = {
            "date": "2024-01-01",
            "overview": "",
            "top_news": [],
        }
        resp = DailySummaryResponse.model_validate(data)
        assert resp.overview == ""
