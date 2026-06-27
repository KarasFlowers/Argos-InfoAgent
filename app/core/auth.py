"""
Simple API Key authentication middleware.

When ``API_KEY`` is set in the environment (or .env), all API requests
must include the header ``X-API-Key: <key>``.  Requests without a matching
key receive a 403 response.

When ``API_KEY`` is unset / empty, the middleware is completely inert —
all requests pass through.  This keeps the local development experience
unchanged.

Routes that are always public (no key required):
  - GET /              (homepage)
  - GET /favicon.ico   (browser icon probe)
  - GET /static/*      (static assets)
  - GET /feed          (public HTML feed)
  - GET /feed/*        (public feed subpages)
  - GET /api/v1/ping   (health check)
  - OPTIONS *          (CORS preflight only; no business side effects)
"""

from __future__ import annotations

import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths that never require authentication. Keep exact and prefix matches
# separate so "/" does not accidentally make every route public.
_PUBLIC_EXACT_PATHS = {"/", "/favicon.ico", "/feed", "/api/v1/ping"}
_PUBLIC_PATH_PREFIXES = ("/static/", "/feed/")


def _api_key_matches(provided: str, expected: str) -> bool:
    """Compare API keys without leaking prefix-match timing."""
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests that don't carry the correct ``X-API-Key`` header."""

    def __init__(self, app, api_key: str | None):
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        # No key configured → everything is open
        if not self._api_key:
            return await call_next(request)

        # Public paths bypass auth
        if self._is_public_path(request.url.path):
            return await call_next(request)

        # CORS preflight must not be rejected before CORSMiddleware can answer.
        if self._is_cors_preflight(request):
            return await call_next(request)

        # Check header
        provided = request.headers.get("X-API-Key", "")
        if _api_key_matches(provided, self._api_key):
            return await call_next(request)

        logger.warning(
            "Rejected request %s %s — invalid or missing X-API-Key",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=403,
            content={"detail": "Invalid or missing API key"},
        )

    @staticmethod
    def _is_public_path(path: str) -> bool:
        return path in _PUBLIC_EXACT_PATHS or any(path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES)

    @staticmethod
    def _is_cors_preflight(request: Request) -> bool:
        return (
            request.method == "OPTIONS"
            and "origin" in request.headers
            and "access-control-request-method" in request.headers
        )
