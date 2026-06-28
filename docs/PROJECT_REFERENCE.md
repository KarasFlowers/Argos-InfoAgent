# Argos Project Reference

This document keeps the detailed reference material that used to live in the README. The README now focuses on the product overview and deployment path.

## More Features

- **Multi-source aggregation**: RSS, Hacker News, Reddit, GitHub, or pure-LLM generated content.
- **Multi-model LLM routing**: separate fast and smart tiers with CircuitBreaker-based resilience.
- **LLM-driven daily briefing**: structured summaries with categories, key points, tags, and topic paths.
- **Daily report refinement**: refine an existing briefing with natural-language instructions.
- **Weekly reports and insights**: topic tree, trending analysis, heatmap, entity timeline, and editorial weekly summary.
- **Content clustering**: Bi-Encoder plus Jaccard fallback grouping of related articles into events.
- **Rule-based filtering**: blacklist keywords/patterns with admin review and restore workflow.
- **Source health monitoring**: track RSS/API source health status with error logging.
- **Cross-source deduplication**: URL normalization plus AI semantic deduplication.
- **URL safety validation**: block private/internal URLs to reduce SSRF risk.
- **Local persistence**: SQLite by default, with optional ChromaDB and Redis cache for fuller offline self-hosting.

## Board Source Types

Each board has a `source_type` that determines how content is fetched.

| Source Type | Description | Example `source_config` |
|-------------|-------------|-------------------------|
| `rss` | Pull from RSS feeds | `{"feeds": ["https://hnrss.org/frontpage"]}` |
| `hackernews` | Fetch HN top stories and comments | `{"fetch_top_stories": 30, "min_score": 100}` |
| `reddit` | Fetch Reddit subreddit/user posts | `{"subreddits": [{"subreddit": "LocalLLaMA"}], "fetch_comments": 5}` |
| `github` | Fetch GitHub user events and repo releases | `{"users": ["openai"], "repos": [{"owner": "openai", "repo": "whisper"}]}` |
| `multi` | Combine multiple source types in parallel | `{"sources": {"rss": {"feeds": [...]}, "hackernews": {"min_score": 50}}}` |
| `pure_llm` | Generate original content with an LLM and no external data | `{"items_per_day": 5, "style": "fun facts"}` |

## MCP Server

Argos exposes capabilities through an MCP (Model Context Protocol) server so AI assistants such as Claude, Cursor, and Windsurf can query briefings, ask RAG questions, and manage preferences.

SQLite limitation: do not run the MCP server alongside the FastAPI web server when using the default SQLite database. Both processes share the same SQLite file, and concurrent writes may cause `database is locked` errors or data corruption. Stop the web server first, or switch to a database setup that supports concurrent access.

Run the stdio server:

```bash
python mcp_server.py
```

Example MCP client config:

```json
{
  "mcpServers": {
    "argos": {
      "command": "python",
      "args": ["path/to/Argos/mcp_server.py"]
    }
  }
}
```

Available tools:

| Tool | Description |
|------|-------------|
| `get_daily_summary` | Read today's briefing for a board. |
| `generate_summary` | Trigger summary generation. |
| `ask_article` | RAG Q&A about any ingested article. |
| `ask_global` | Cross-article RAG Q&A across ingested content. |
| `search_news` | Keyword search across news history. |
| `list_boards` | List content boards. |
| `add_feedback` | Like/dislike articles for personalization. |
| `get_user_interests` | View persona and preferences. |
| `get_system_status` | System health and configuration summary. |
| `deep_research` | Decompose a question and synthesize a structured report. |
| `get_weekly_report` | Generate a structured weekly report. |
| `get_topic_tree` | Build a hierarchical topic tree from article topic paths. |
| `get_trending_topics` | Find upward-trending topics for a period. |
| `get_cost_breakdown` | Per-label LLM token usage breakdown. |

## Architecture

The service layer uses facade modules for backward-compatible imports while allowing larger modules to be split internally.

| Facade | Main Implementation | Exports |
|--------|---------------------|---------|
| `llm_service.py` | `app/services/llm/` | `LLMService`, `llm_service` |
| `rag_service.py` | `app/services/rag/_core.py` | Public RAG functions |
| `db_service.py` | `app/services/repositories/` | `DBService`, `db_service` |

New code should prefer concrete subpackages, for example `from app.services.llm import LLMService`, instead of importing from compatibility facades.

Main internal areas:

- **LLM service**: scoring, summary, weekly, and wizard mixins plus `LLMClient`, CircuitBreaker, and multi-tier model routing.
- **RAG service**: hybrid retrieval pipeline, Cross-Encoder reranking, HyDE rewriting, background ingestion, and cross-article search.
- **Repositories**: summary, persona, read-state, source, and board data access.
- **Notification**: email dispatcher; unsupported channels fail closed.
- **Source adapters**: `rss`, `hackernews`, `reddit`, `github`, `multi`, and `pure_llm`.

## Project Structure

```text
.
├── app/
│   ├── api/                    # FastAPI routers
│   ├── core/                   # Config, DB, HTTP client, scheduler, auth, logging, URL safety
│   ├── models/                 # SQLModel domain models and Pydantic schemas
│   ├── prompts/                # LLM prompt templates
│   ├── scrapers/               # HN, Reddit, and GitHub scrapers
│   ├── services/               # Business logic, integrations, repositories
│   └── web/                    # Jinja templates and static assets
├── alembic/                    # Database migrations
├── docs/                       # Design, operations, and audit notes
├── scripts/                    # Launchers, smoke checks, backup/restore helpers
├── tests/                      # Pytest suite
└── tools/                      # Local helper tools
```

Runtime data lives under `data/`, `logs/`, and local cache directories. These are ignored by Git and should not be committed.

## Key Files

| Path | Description |
|------|-------------|
| `main.py` | FastAPI app entry point. |
| `mcp_server.py` | MCP server entry point. |
| `app/core/config.py` | Settings, environment variables, and defaults. |
| `app/core/db.py` | Async database engine, sessions, migrations, and seeding. |
| `app/core/scheduler.py` | APScheduler jobs with task-run tracking. |
| `app/models/domain.py` | SQLModel tables. |
| `app/models/schemas.py` | Request/response schemas and tolerant LLM output parsing. |
| `app/models/source_configs.py` | Per-source board config validation. |
| `app/prompts/` | Prompt templates. |
| `app/web/static/` | Frontend assets. |
| `app/web/templates/` | HTML templates. |
| `scripts/Open_Web_Dashboard.bat` | Windows launcher. |
| `scripts/start.sh` | macOS/Linux launcher. |
| `scripts/download_models.py` | RAG model downloader. |

## Tech Stack

- **Backend**: FastAPI, SQLModel, APScheduler, Alembic.
- **LLM**: OpenAI-compatible APIs through a configurable `LLMClient`.
- **RAG**: Sentence Transformers, ChromaDB, BM25, Cross-Encoder reranking, HyDE.
- **MCP**: FastMCP and Model Context Protocol.
- **Database/cache**: SQLite via aiosqlite, optional Redis cache, and optional ChromaDB for RAG.
- **Scraping**: httpx, feedparser, BeautifulSoup, trafilatura.
- **Logging**: structlog.
- **Templating**: Jinja2 for HTML and prompts.

## API Map

Private endpoints use the `/api/v1` prefix unless noted. When `API_KEY` is set, private requests must include `X-API-Key`. `/api/v1/ping` stays public for health checks, and `OPTIONS` stays open for CORS preflight.

### Briefing and Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/summary` | Get or generate daily summary. |
| GET | `/briefing` | Structured briefing with sections and clusters. |
| POST | `/briefing/refine` | Refine an existing briefing with an instruction. |
| GET | `/briefing/refine/{session_id}` | Check refinement status. |
| GET | `/history` | Summary history archive. |
| GET | `/history/weekly_insight` | AI-generated weekly insight. |
| GET | `/history/weekly_report` | Structured weekly report. |

### Boards

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/boards` | List boards. |
| POST | `/boards` | Create a board. |
| GET | `/boards/{slug}` | Get board details. |
| PATCH | `/boards/{slug}` | Update board settings. |
| DELETE | `/boards/{slug}` | Soft-delete a board. |
| GET | `/boards/{slug}/perspectives` | List available perspectives. |
| POST | `/boards/wizard` | AI-guided board wizard. |

### Persona, Preferences, and Feedback

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/persona` | List persona instructions. |
| POST | `/persona` | Add persona instruction. |
| DELETE | `/persona/{id}` | Delete persona instruction. |
| GET | `/persona/inferred` | AI-inferred interests from feedback. |
| GET | `/preferences` | Explicit preferences and memory. |
| POST | `/feedback/interest-options` | Get suggested interest options. |
| POST | `/feedback/save-reason` | Save an interest reason. |

### RAG

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/rag/ingest` | Ingest a URL into the vector store. |
| GET | `/rag/ingest_status` | Check background ingestion status. |
| POST | `/rag/overview` | Generate article overview. |
| POST | `/rag/query` | RAG Q&A with SSE streaming. |
| POST | `/rag/query/global` | Cross-article RAG Q&A with SSE streaming. |
| GET | `/rag/history` | Chat history for an article. |
| POST | `/rag/feedback` | Record feedback. |

### Insights, Research, and Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/insights/heatmap` | Category frequency heatmap. |
| GET | `/insights/timeline` | Entity occurrence timeline. |
| GET | `/insights/topic_tree` | Hierarchical topic tree. |
| GET | `/insights/trending` | Trending topics analysis. |
| POST | `/research` | Deep research cycle. |
| GET | `/ping` | Public health check. |
| GET | `/status` | Private readiness diagnostics without secrets. |
| GET | `/metrics` | Token usage and latency metrics. |
| GET | `/metrics/cost` | Per-label LLM cost breakdown. |
| GET | `/admin/tasks` | Background task history. |
| GET | `/admin/sources/health` | Source health dashboard. |
| GET | `/admin/sources/{id}/health_log` | Source health log entries. |
| GET | `/feeds` | Manually fetch RSS feeds. |
| POST | `/sources/test` | Test one RSS feed URL. |

### Public Pages

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard. |
| GET | `/feed` | Public feed page. |

## Operations Notes

- Keep `PUBLIC_BASE_URL` aligned with the external URL when serving RSS/feed links behind a reverse proxy.
- Back up `data/sqlite/argos.db` and `data/chroma/` together with `python scripts/backup_data.py`.
- Before restoring, stop Argos and run `python scripts/restore_data.py backups/<archive>.zip --dry-run`; use `--force` only when replacing existing local data.
- `RAG_ENABLED=false` is the default lightweight deployment. Set it to `true` only when article-level RAG and local embedding models are needed.
- Scheduled external notifications are disabled by default. Set `NOTIFY_CHANNELS=email` and SMTP settings explicitly before enabling email push.
- Track release-hardening evidence in [docs/INDUSTRIALIZATION_AUDIT.md](INDUSTRIALIZATION_AUDIT.md).

## 中文速览

这份文档承接 README 中移出的详细参考信息。README 只保留功能介绍、部署流程、安全边界和必要入口；完整功能、MCP、架构、API 和运维说明集中放在这里，便于维护者和贡献者查阅。
