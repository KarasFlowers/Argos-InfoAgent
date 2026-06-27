"""GitHub scraper — ported from Horizon."""

import logging
import os
from datetime import datetime

import httpx

from app.models.schemas import ContentItem
from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class GitHubScraper(BaseScraper):
    """Scraper for GitHub user events and repo releases.

    Expected config shape::

        {
            "enabled": true,
            "users": [
                {"username": "torvalds", "enabled": true}
            ],
            "repos": [
                {"owner": "openai", "repo": "whisper", "enabled": true}
            ]
        }
    """

    def __init__(self, config: dict, http_client: httpx.AsyncClient):
        super().__init__(config, http_client)
        from app.core.config import settings

        self.token = settings.GITHUB_TOKEN or os.getenv("GITHUB_TOKEN")
        self.base_url = "https://api.github.com"

    def _get_headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Argos-Scraper",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    async def fetch(self, since: datetime) -> list[ContentItem]:
        if not self.config.get("enabled", True):
            return []

        items: list[ContentItem] = []

        for user_cfg in self.config.get("users", []):
            if not user_cfg.get("enabled", True):
                continue
            username = user_cfg.get("username", "")
            if username:
                items.extend(await self._fetch_user_events(username, since))

        for repo_cfg in self.config.get("repos", []):
            if not repo_cfg.get("enabled", True):
                continue
            owner = repo_cfg.get("owner", "")
            repo = repo_cfg.get("repo", "")
            if owner and repo:
                items.extend(await self._fetch_repo_releases(owner, repo, since))

        return items

    async def _fetch_user_events(self, username: str, since: datetime) -> list[ContentItem]:
        url = f"{self.base_url}/users/{username}/events/public"
        items: list[ContentItem] = []

        try:
            resp = await self.client.get(url, headers=self._get_headers(), follow_redirects=True)
            resp.raise_for_status()
            events = resp.json()

            for event in events:
                created_at = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
                if created_at < since:
                    continue

                event_type = event["type"]
                if event_type not in (
                    "PushEvent",
                    "CreateEvent",
                    "ReleaseEvent",
                    "PublicEvent",
                    "WatchEvent",
                ):
                    continue

                item = self._parse_event(event, username)
                if item:
                    items.append(item)
        except httpx.HTTPError as e:
            logger.warning("Error fetching GitHub events for %s: %s", username, e)

        return items

    def _parse_event(self, event: dict, username: str) -> ContentItem | None:
        event_type = event["type"]
        event_id = event["id"]
        created_at = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
        repo_name = event["repo"]["name"]
        repo_url = f"https://github.com/{repo_name}"

        if event_type == "PushEvent":
            commits = event["payload"].get("commits", [])
            title = f"{username} pushed {len(commits)} commit(s) to {repo_name}"
            content = "\n".join(c.get("message", "") for c in commits[:3])
        elif event_type == "CreateEvent":
            ref_type = event["payload"].get("ref_type", "repository")
            title = f"{username} created {ref_type} in {repo_name}"
            content = event["payload"].get("description", "") or ""
        elif event_type == "ReleaseEvent":
            release = event["payload"].get("release", {})
            title = f"{username} released {release.get('tag_name', '')} in {repo_name}"
            content = release.get("body", "") or ""
            repo_url = release.get("html_url", repo_url)
        elif event_type == "PublicEvent":
            title = f"{username} made {repo_name} public"
            content = ""
        elif event_type == "WatchEvent":
            title = f"{username} starred {repo_name}"
            content = ""
        else:
            return None

        return ContentItem(
            id=self._generate_id("github", "event", event_id),
            source_type="github",
            title=title,
            url=repo_url,
            content=content,
            author=username,
            published_at=created_at.isoformat(),
            source_name=repo_name,
            metadata={"event_type": event_type, "repo": repo_name},
        )

    async def _fetch_repo_releases(self, owner: str, repo: str, since: datetime) -> list[ContentItem]:
        url = f"{self.base_url}/repos/{owner}/{repo}/releases"
        items: list[ContentItem] = []

        try:
            resp = await self.client.get(url, headers=self._get_headers(), follow_redirects=True)
            resp.raise_for_status()
            releases = resp.json()

            for release in releases:
                published_at = datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
                if published_at < since:
                    continue

                items.append(
                    ContentItem(
                        id=self._generate_id("github", "release", str(release["id"])),
                        source_type="github",
                        title=f"{owner}/{repo} released {release['tag_name']}",
                        url=release["html_url"],
                        content=release.get("body", "") or "",
                        author=release["author"]["login"],
                        published_at=published_at.isoformat(),
                        source_name=f"{owner}/{repo}",
                        metadata={
                            "repo": f"{owner}/{repo}",
                            "tag": release["tag_name"],
                            "prerelease": release.get("prerelease", False),
                        },
                    )
                )
        except httpx.HTTPError as e:
            logger.warning("Error fetching releases for %s/%s: %s", owner, repo, e)

        return items
