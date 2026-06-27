"""
Pydantic schemas for per-source-type board configuration.

Used by the API router to validate ``source_config`` on board
create / update, and optionally by adapters for stricter parsing.
"""

from pydantic import BaseModel, Field

# ---- RSS ----


class RSSConfig(BaseModel):
    feeds: list[str] = Field(default_factory=list, description="RSS feed URLs")


# ---- Hacker News ----


class HNConfig(BaseModel):
    fetch_top_stories: int = Field(default=30, ge=1, le=100)
    min_score: int = Field(default=100, ge=0)


# ---- Reddit ----


class SubredditSpec(BaseModel):
    subreddit: str = Field(min_length=1)
    sort: str = Field(default="hot")
    time_filter: str = Field(default="day")
    fetch_limit: int = Field(default=25, ge=1, le=100)
    min_score: int = Field(default=10, ge=0)


class UserSpec(BaseModel):
    username: str = Field(min_length=1)
    sort: str = Field(default="new")
    fetch_limit: int = Field(default=10, ge=1, le=100)


class RedditConfig(BaseModel):
    subreddits: list[SubredditSpec] = Field(default_factory=list)
    users: list[UserSpec] = Field(default_factory=list)
    fetch_comments: int = Field(default=5, ge=0, le=25)


# ---- GitHub ----


class RepoSpec(BaseModel):
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)


class GitHubConfig(BaseModel):
    users: list[str] = Field(default_factory=list, description="GitHub usernames")
    repos: list[RepoSpec] = Field(default_factory=list)


# ---- Multi ----


class MultiSourceConfig(BaseModel):
    sources: dict = Field(
        default_factory=dict,
        description="Keys are source type names, values are their configs",
    )


# ---- Pure LLM ----


class PureLLMConfig(BaseModel):
    items_per_day: int = Field(default=5, ge=1, le=15)
    style: str = Field(default="")


# ---- Registry: source_type -> config class ----

SOURCE_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "rss": RSSConfig,
    "hackernews": HNConfig,
    "reddit": RedditConfig,
    "github": GitHubConfig,
    "multi": MultiSourceConfig,
    "pure_llm": PureLLMConfig,
}
