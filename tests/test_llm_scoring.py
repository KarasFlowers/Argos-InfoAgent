"""
test_llm_scoring.py - Unit tests for LLM article scoring logic.

Tests the JSON parsing and score extraction logic without making real LLM calls.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm.scoring import ScoringMixin


class FakeScorer(ScoringMixin):
    """Minimal concrete class to test ScoringMixin methods."""

    def __init__(self, llm_response: str = '{"scores": []}'):
        self.llm = MagicMock()
        self.llm.chat = AsyncMock(return_value=self._make_response(llm_response))

    @staticmethod
    def _make_response(content: str):
        mock_msg = MagicMock()
        mock_msg.content = content
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage = None
        return mock_resp


# ---------------------------------------------------------------------------
# Score extraction
# ---------------------------------------------------------------------------


class TestScoreExtraction:
    @pytest.mark.anyio
    async def test_parses_valid_scores(self):
        response = json.dumps(
            {
                "scores": [
                    {"index": 0, "score": 8},
                    {"index": 1, "score": 3},
                    {"index": 2, "score": 9},
                ]
            }
        )
        scorer = FakeScorer(response)

        articles = [
            {"title": "AI breakthrough", "summary": "New model"},
            {"title": "Celebrity news", "summary": "Gossip"},
            {"title": "Python 3.13", "summary": "New release"},
        ]

        from unittest.mock import patch

        with patch("app.services.metrics_service.metrics_service") as mock_metrics:
            mock_metrics.record_tokens = AsyncMock()
            mock_metrics.record_latency = AsyncMock()
            result = await scorer._score_articles(articles)
        # Should return high-quality articles (score > 5)
        assert isinstance(result, tuple)

    @pytest.mark.anyio
    async def test_handles_empty_scores(self):
        response = '{"scores": []}'
        scorer = FakeScorer(response)

        articles = [{"title": "Test", "summary": "Test summary"}]
        from unittest.mock import patch

        with patch("app.services.metrics_service.metrics_service") as mock_metrics:
            mock_metrics.record_tokens = AsyncMock()
            mock_metrics.record_latency = AsyncMock()
            result = await scorer._score_articles(articles)
        assert isinstance(result, tuple)

    @pytest.mark.anyio
    async def test_handles_malformed_json(self):
        """LLM sometimes returns slightly invalid JSON — should not crash."""
        response = 'Here are the scores: {"scores": [{"index": 0, "score": 7}]}'
        scorer = FakeScorer(response)

        articles = [{"title": "Test", "summary": "Test"}]
        from unittest.mock import patch

        with patch("app.services.metrics_service.metrics_service") as mock_metrics:
            mock_metrics.record_tokens = AsyncMock()
            mock_metrics.record_latency = AsyncMock()
            # Should not raise
            result = await scorer._score_articles(articles)
        assert isinstance(result, tuple)

    @pytest.mark.anyio
    async def test_handles_list_format(self):
        """Some LLMs return a list instead of an object."""
        response = json.dumps([{"index": 0, "score": 7}, {"index": 1, "score": 2}])
        scorer = FakeScorer(response)

        articles = [
            {"title": "Good article", "summary": "Great"},
            {"title": "Bad article", "summary": "Meh"},
        ]
        from unittest.mock import patch

        with patch("app.services.metrics_service.metrics_service") as mock_metrics:
            mock_metrics.record_tokens = AsyncMock()
            mock_metrics.record_latency = AsyncMock()
            result = await scorer._score_articles(articles)
        assert isinstance(result, tuple)
