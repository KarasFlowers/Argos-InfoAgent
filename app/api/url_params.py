from fastapi import HTTPException


def normalize_source_url_or_400(value: str | None) -> str:
    """Normalize a user-submitted RSS URL and reject non-HTTP(S) schemes."""
    from urllib.parse import urlparse

    url = (value or "").strip()
    parsed = urlparse(url)
    if not url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Source URL must be a valid http(s) URL.")
    return url


def normalize_article_url_or_400(value: str | None) -> str:
    """Normalize an article URL-like identifier while allowing internal schemes."""
    url = (value or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Article URL cannot be empty.")
    return url
