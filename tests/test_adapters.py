"""
test_adapters.py - Tests for source adapter registry.

Verifies that all new adapters are registered and retrievable.
"""

import pytest

from app.services.source_adapters import UnknownSourceTypeError, get_adapter


@pytest.mark.parametrize(
    "source_type",
    ["rss", "pure_llm", "hackernews", "reddit", "github", "multi"],
)
def test_registered_adapters(source_type):
    """All expected source types should be registered and retrievable."""
    adapter = get_adapter(source_type)
    assert adapter is not None
    assert adapter.source_type == source_type


def test_unknown_adapter_raises():
    """Requesting an unregistered source type should raise UnknownSourceTypeError."""
    with pytest.raises(UnknownSourceTypeError):
        get_adapter("nonexistent_source")
