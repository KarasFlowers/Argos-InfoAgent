"""Unit tests for RSS feed autodiscovery parsing (_parse_feed_links).

The pure, synchronous core of the wizard's source-discovery stage: given a
homepage's HTML, extract the advertised RSS/Atom feed URLs.
"""

from app.api.routes.sources import parse_feed_links


def test_finds_rss_and_atom_links():
    html = """
    <html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml">
      <link rel="alternate" type="application/atom+xml" href="https://x.com/atom">
    </head></html>
    """
    feeds = parse_feed_links(html, "https://example.com/blog")
    assert "https://example.com/feed.xml" in feeds
    assert "https://x.com/atom" in feeds
    assert len(feeds) == 2


def test_resolves_relative_href_against_base():
    html = '<link rel="alternate" type="application/rss+xml" href="rss">'
    feeds = parse_feed_links(html, "https://example.com/sub/page")
    assert feeds == ["https://example.com/sub/rss"]


def test_filters_private_feed_links_from_candidates():
    html = """
    <link rel="alternate" type="application/rss+xml" href="http://localhost/feed.xml">
    <link rel="alternate" type="application/rss+xml" href="http://192.168.1.5/feed.xml">
    <link rel="alternate" type="application/rss+xml" href="/public-feed.xml">
    """
    feeds = parse_feed_links(html, "https://example.com/sub/page")
    assert feeds == ["https://example.com/public-feed.xml"]


def test_ignores_non_feed_links():
    html = """
    <link rel="stylesheet" type="text/css" href="/style.css">
    <link rel="icon" href="/favicon.ico">
    <link rel="alternate" type="text/html" href="/amp">
    """
    assert parse_feed_links(html, "https://example.com") == []


def test_no_feeds_returns_empty():
    assert parse_feed_links("<html><head></head></html>", "https://example.com") == []


def test_dedupes_repeated_feeds():
    html = """
    <link rel="alternate" type="application/rss+xml" href="/feed">
    <link rel="alternate" type="application/rss+xml" href="/feed">
    """
    assert parse_feed_links(html, "https://example.com") == ["https://example.com/feed"]


def test_respects_limit():
    links = "".join(f'<link rel="alternate" type="application/rss+xml" href="/feed{i}">' for i in range(10))
    feeds = parse_feed_links(links, "https://example.com", limit=3)
    assert len(feeds) == 3


def test_malformed_html_never_raises():
    # Garbage input must degrade to [] rather than propagating an exception.
    assert parse_feed_links("<<<not html>>> <link rel=", "https://example.com") == []


def test_handles_uppercase_type_and_rel():
    html = '<link REL="ALTERNATE" TYPE="application/rss+xml" href="/feed">'
    assert parse_feed_links(html, "https://example.com") == ["https://example.com/feed"]
