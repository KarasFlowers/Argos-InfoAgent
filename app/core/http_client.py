"""
Shared httpx.AsyncClient singleton.

All adapters and scrapers should use ``get_http_client()`` instead of
creating a new ``httpx.AsyncClient`` per request, so that connection
pooling is effective across the application.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

_shared_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the shared async HTTP client (lazy-created)."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            },
            follow_redirects=True,
        )
        logger.debug("Created shared httpx.AsyncClient")
    return _shared_client


async def close_http_client() -> None:
    """Gracefully close the shared client (call on app shutdown)."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
        logger.debug("Closed shared httpx.AsyncClient")
    _shared_client = None
