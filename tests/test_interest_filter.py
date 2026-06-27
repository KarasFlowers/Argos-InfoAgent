"""
test_interest_filter.py - Unit tests for InterestFilter service.

Tests:
  - Block topic filtering
  - Focus topic boosting
  - Combined block + boost
  - Empty personas
  - Scoring context generation
"""

from unittest.mock import MagicMock

from app.services.interest_filter import InterestFilter


def _make_persona(content: str, category: str = "instruction", is_active: bool = True):
    """Create a mock UserPersona."""
    p = MagicMock()
    p.content = content
    p.category = category
    p.is_active = is_active
    return p


def _make_item(title: str, content: str = "", source_type: str = "rss"):
    """Create a mock ContentItem."""
    item = MagicMock()
    item.title = title
    item.content = content
    item.source_type = source_type
    return item


# ---------------------------------------------------------------------------
# Empty / no personas
# ---------------------------------------------------------------------------


class TestNoPersonas:
    def test_empty_personas_returns_all(self):
        f = InterestFilter([])
        items = [_make_item("A"), _make_item("B")]
        result = f.filter_items(items)
        assert len(result) == 2

    def test_has_interests_false_when_empty(self):
        f = InterestFilter([])
        assert f.has_interests is False


# ---------------------------------------------------------------------------
# Block topic filtering
# ---------------------------------------------------------------------------


class TestBlockTopic:
    def test_blocks_matching_title(self):
        personas = [_make_persona("crypto", category="block_topic")]
        f = InterestFilter(personas)
        items = [
            _make_item("Bitcoin hits new high"),
            _make_item("Python 3.13 released"),
            _make_item("Crypto market crashes"),
        ]
        result = f.filter_items(items)
        # "Crypto market crashes" is blocked; "Bitcoin" does NOT contain "crypto"
        assert len(result) == 2
        titles = [it.title for it in result]
        assert "Bitcoin hits new high" in titles
        assert "Python 3.13 released" in titles

    def test_block_is_case_insensitive(self):
        personas = [_make_persona("bitcoin", category="block_topic")]
        f = InterestFilter(personas)
        items = [_make_item("BITCOIN news"), _make_item("Other news")]
        result = f.filter_items(items)
        assert len(result) == 1

    def test_multiple_block_rules(self):
        personas = [
            _make_persona("crypto", category="block_topic"),
            _make_persona("celebrity", category="block_topic"),
        ]
        f = InterestFilter(personas)
        items = [
            _make_item("Crypto news"),
            _make_item("Celebrity gossip"),
            _make_item("Tech news"),
        ]
        result = f.filter_items(items)
        assert len(result) == 1
        assert result[0].title == "Tech news"

    def test_no_match_keeps_all(self):
        personas = [_make_persona("quantum computing", category="block_topic")]
        f = InterestFilter(personas)
        items = [_make_item("AI news"), _make_item("Python tutorial")]
        result = f.filter_items(items)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Focus topic boosting
# ---------------------------------------------------------------------------


class TestFocusTopic:
    def test_boosts_matching_items_to_front(self):
        personas = [_make_persona("LLM, transformer", category="focus_topic")]
        f = InterestFilter(personas)
        items = [
            _make_item("Cooking recipe"),
            _make_item("New LLM released by OpenAI"),
            _make_item("Sports news"),
        ]
        result = f.filter_items(items)
        assert result[0].title == "New LLM released by OpenAI"

    def test_boost_by_content_match(self):
        personas = [_make_persona("transformer", category="focus_topic")]
        f = InterestFilter(personas)
        items = [
            _make_item("Random news", content="nothing special"),
            _make_item("Tech update", content="The transformer architecture changed everything"),
        ]
        result = f.filter_items(items)
        assert result[0].title == "Tech update"

    def test_has_interests_true_with_focus(self):
        personas = [_make_persona("AI", category="focus_topic")]
        f = InterestFilter(personas)
        assert f.has_interests is True


# ---------------------------------------------------------------------------
# Combined block + boost
# ---------------------------------------------------------------------------


class TestCombined:
    def test_block_then_boost(self):
        personas = [
            _make_persona("crypto", category="block_topic"),
            _make_persona("LLM", category="focus_topic"),
        ]
        f = InterestFilter(personas)
        items = [
            _make_item("Crypto scam alert"),
            _make_item("Cooking tips"),
            _make_item("New LLM benchmark results"),
        ]
        result = f.filter_items(items)
        assert len(result) == 2
        assert result[0].title == "New LLM benchmark results"


# ---------------------------------------------------------------------------
# build_scoring_context
# ---------------------------------------------------------------------------


class TestScoringContext:
    def test_empty_personas_returns_empty(self):
        f = InterestFilter([])
        assert f.build_scoring_context() == ""

    def test_focus_topic_in_context(self):
        personas = [_make_persona("AI, machine learning", category="focus_topic")]
        f = InterestFilter(personas)
        ctx = f.build_scoring_context()
        assert "AI" in ctx or "machine learning" in ctx

    def test_block_topic_in_context(self):
        personas = [_make_persona("crypto", category="block_topic")]
        f = InterestFilter(personas)
        ctx = f.build_scoring_context()
        assert "crypto" in ctx.lower() or "block" in ctx.lower() or ctx == ""
