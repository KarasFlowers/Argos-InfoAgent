import pytest
from fastapi import HTTPException

from app.api.url_params import normalize_article_url_or_400, normalize_source_url_or_400


def test_normalize_source_url_accepts_http_urls():
    assert normalize_source_url_or_400(" https://example.com/feed ") == "https://example.com/feed"


def test_normalize_source_url_rejects_non_http_urls():
    with pytest.raises(HTTPException) as exc_info:
        normalize_source_url_or_400("file:///etc/passwd")

    assert exc_info.value.status_code == 400


def test_normalize_article_url_allows_internal_ids():
    assert normalize_article_url_or_400(" llm://board/date/1 ") == "llm://board/date/1"


def test_normalize_article_url_rejects_empty_values():
    with pytest.raises(HTTPException) as exc_info:
        normalize_article_url_or_400("   ")

    assert exc_info.value.status_code == 400
