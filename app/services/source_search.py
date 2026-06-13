"""Platform-native source search — replace LLM guessing with real lookups.

The board wizard previously asked the LLM to *guess* subreddit names and GitHub
repos, then validated them. These helpers instead query each platform's own
search API, so existence is guaranteed and results carry popularity signals
(subscribers / stars) usable for ranking. No Tavily needed.

Both functions never raise — on any failure they return ``[]``, matching the
discovery layer's degrade-gracefully style.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


async def search_subreddits(query: str, limit: int = 5) -> list[dict]:
    """Search real subreddits via Reddit's public search API.

    Returns ``[{name, title, subscribers}]`` sorted by subscriber count desc.
    """
    import httpx

    query = (query or "").strip()
    if not query:
        return []

    headers = {"User-Agent": _UA, "Accept": "application/json"}
    params = {"q": query, "limit": min(max(limit, 1), 25), "raw_json": 1}
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.reddit.com/subreddits/search.json",
                params=params, timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.debug("search_subreddits failed for '%s': %s", query, e)
        return []

    out: list[dict] = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        name = d.get("display_name")
        if not name:
            continue
        out.append({
            "name": name,
            "title": d.get("title", ""),
            "subscribers": d.get("subscribers") or 0,
        })
    out.sort(key=lambda s: s["subscribers"], reverse=True)
    return out[:limit]


async def search_github_repos(query: str, limit: int = 5) -> list[dict]:
    """Search real GitHub repos via the search API, sorted by stars.

    Returns ``[{owner, repo, stars, description}]``. Reuses ``GITHUB_TOKEN``
    when configured to raise the rate limit.
    """
    import httpx
    from app.core.config import settings

    query = (query or "").strip()
    if not query:
        return []

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Argos-Wizard",
    }
    token = getattr(settings, "GITHUB_TOKEN", None)
    if token:
        headers["Authorization"] = f"token {token}"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(max(limit, 1), 20)}

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.github.com/search/repositories",
                params=params, timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.debug("search_github_repos failed for '%s': %s", query, e)
        return []

    out: list[dict] = []
    for item in data.get("items", []):
        full = item.get("full_name", "")
        if "/" not in full:
            continue
        owner, repo = full.split("/", 1)
        out.append({
            "owner": owner,
            "repo": repo,
            "stars": item.get("stargazers_count") or 0,
            "description": (item.get("description") or "")[:200],
        })
    return out[:limit]
