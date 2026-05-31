# Argos

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com)

**[English](README.md) | [Chinese](README_zh.md)**

> An intelligent daily tech briefing assistant powered by LLM and RAG — with multi-board management, article-level RAG Q&A, deep research, and MCP integration.

Argos is a FastAPI-based daily tech briefing application that aggregates content from multiple sources (RSS, Hacker News, Reddit, GitHub, or pure LLM), uses any OpenAI-compatible LLM to curate structured summaries, and provides article-level RAG chat with feedback-driven personalization. Each board runs independently with its own sources, prompts, persona, and notification channels.

## ✨ Highlight Features

### 🧩 Board System

Create custom sections (boards) — each with its own source type, system prompt, persona, schedule, and notification channels. The AI-guided **Board Wizard** helps you configure new boards in seconds.

### 🔍 Article-Level RAG

Hybrid retrieval pipeline combining Bi-Encoder + BM25 with **Cross-Encoder reranking** and **HyDE query rewriting**. Supports both single-article and **cross-article** Q&A over all ingested content.

### 🔬 Deep Research

Decompose a complex question into sub-queries, search RAG + web sources, then synthesize a structured research report — all in one click.

### 🤖 MCP Server

Expose all capabilities to AI assistants (Claude, Cursor, Windsurf, etc.) via the [Model Context Protocol](https://modelcontextprotocol.io/) — 14 tools for briefings, RAG, research, and preferences.

### 🎯 Personalized Recommendations

Explicit like/dislike feedback + auto-extracted interests + **user memory system** (persistent preferences and context). The more you use it, the better it knows you.

### 📢 Multi-Channel Notifications

Push daily briefings via **email, Webhook, Bark (iOS), or Telegram** — automatically on schedule or on demand.

---

## More Features

- **Multi-source aggregation** — RSS, Hacker News, Reddit, GitHub, or pure-LLM generated content
- **Multi-model LLM routing** — Separate "fast" and "smart" tiers with CircuitBreaker for resilient calls
- **LLM-driven daily briefing** — Structured summaries with categories, key points, tags, and topic paths
- **Daily report refinement** — Iteratively refine an existing briefing with natural-language instructions
- **Weekly reports & insights** — Topic tree, trending analysis, heatmap, entity timeline, and editorial weekly summary
- **Content clustering** — Bi-Encoder + Jaccard fallback grouping of related articles into events
- **Rule-based filtering** — Blacklist keywords/patterns with admin review and restore workflow
- **Source health monitoring** — Track RSS/API source health status with error logging
- **Cross-source deduplication** — URL normalization + AI semantic deduplication
- **URL safety validation** — Block private/internal URLs to prevent SSRF
- **Local persistence** — SQLite, ChromaDB, and Redis cache for offline-first design

## Demo

Argos provides a web dashboard at `http://127.0.0.1:8000` for browsing daily briefings, chatting with articles via RAG, managing boards, and tracking insights. A public SEO-friendly feed page is available at `/feed`.

## Quick Start

### Prerequisites

- Python 3.11+
- [Redis](https://redis.io/) (for caching)
- An OpenAI-compatible LLM API key (e.g. [DeepSeek](https://platform.deepseek.com/), OpenAI, etc.)

### Docker (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. Configure environment
cp .env.template .env
# Edit .env and set LLM_API_KEY (or DEEPSEEK_API_KEY for legacy compat)

# 3. Start the stack
docker compose up -d

# 4. Open in browser
# Visit http://127.0.0.1:8000
```

### One-Click Start (Recommended for Local)

The project ships with launcher scripts that handle **venv creation, dependency installation, .env setup, Redis, model download, and browser opening** automatically:

```bash
# macOS / Linux
chmod +x scripts/start.sh
./scripts/start.sh

# Windows — double-click or run:
scripts\Open_Web_Dashboard.bat
```

On first run the script will:
1. Create a virtual environment and install dependencies
2. Prompt you to enter your LLM API key (creates `.env` automatically)
3. Check/start Redis
4. Pre-download RAG embedding models (~650 MB, one-time)
5. Start the backend and open the dashboard in your browser

### Manual Setup

<details>
<summary>Click to expand step-by-step instructions</summary>

```bash
# 1. Clone the repository
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.template .env
# Edit .env and set LLM_API_KEY (or DEEPSEEK_API_KEY for legacy compat)

# 5. (Optional) Pre-download RAG models to avoid first-request delay
python scripts/download_models.py

# 6. Start Redis (if not already running)
# Windows: the .bat launcher handles this automatically
# Linux / macOS: redis-server --daemonize yes

# 7. Start the application
uvicorn main:app --reload

# 8. Open http://127.0.0.1:8000 in your browser
```

</details>

## Configuration

Copy `.env.template` to `.env` and configure your settings. At minimum, you need to set `LLM_API_KEY` (or the legacy `DEEPSEEK_API_KEY`).

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_API_KEY` | **Yes** | - | API key for any OpenAI-compatible LLM provider |
| `LLM_MODEL` | No | `deepseek-chat` | Default model name for all LLM calls |
| `LLM_BASE_URL` | No | `https://api.deepseek.com/v1` | Base URL of the LLM API |
| `LLM_TIMEOUT` | No | `180` | Request timeout in seconds |
| `LLM_MAX_RETRIES` | No | `1` | Max retries on transient failures |
| `FAST_LLM` | No | - | "fast" tier model in `provider:model` format (e.g. `openai:gpt-4o-mini`). Empty = fall back to `LLM_MODEL` |
| `SMART_LLM` | No | - | "smart" tier model in `provider:model` format. Empty = fall back to `LLM_MODEL` |
| `DEEPSEEK_API_KEY` | No | - | Legacy alias — used as fallback when `LLM_API_KEY` is unset |
| `API_KEY` | No | - | API key for authenticating `/api/v1/*` requests (via `X-API-Key` header). Unset = no auth |
| `SQLALCHEMY_DATABASE_URI` | No | `sqlite+aiosqlite:///./data/sqlite/argos.db` | Async SQLite database path |
| `CHROMA_DB_DIR` | No | `./data/chroma` | ChromaDB persistent storage path |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis connection URL for caching |
| `RAG_BACKGROUND_INGEST_ENABLED` | No | `True` | Enable background RAG ingestion pipeline |
| `RAG_BACKGROUND_INGEST_WORKERS` | No | `2` | Number of background ingest worker tasks |
| `RAG_HYDE_ENABLED` | No | `True` | Enable HyDE (Hypothetical Document Embedding) query rewriting |
| `HISTORY_DAYS_TO_KEEP` | No | `7` | Number of days to retain historical data |
| `CORS_ORIGINS` | No | `http://localhost:3000,...` | Comma-separated allowed frontend origins |
| `GITHUB_TOKEN` | No | - | GitHub personal access token (increases rate limit to 5000 req/hr) |
| `HN_FETCH_TOP_STORIES` | No | `30` | Number of top Hacker News stories to fetch |
| `HN_MIN_SCORE` | No | `100` | Minimum Hacker News score threshold |
| `REDDIT_FETCH_COMMENTS` | No | `5` | Top comments to include per Reddit post |
| `SMTP_HOST` | No | - | SMTP server for email push |
| `SMTP_PORT` | No | `465` | SMTP server port |
| `SMTP_USER` | No | - | SMTP username |
| `SMTP_PASSWORD` | No | - | SMTP password |
| `SMTP_FROM` | No | - | Sender email address (e.g. `Argos <you@example.com>`) |
| `EMAIL_SUBSCRIBERS` | No | `[]` | JSON list of subscriber email addresses |
| `DAILY_PUSH_TIME` | No | `08:00` | Daily push time (HH:MM format) |
| `NOTIFY_CHANNELS` | No | `email` | Comma-separated channels: `email,webhook,bark,telegram` |
| `WEBHOOK_URL` | No | - | Generic webhook endpoint (POST JSON) |
| `WEBHOOK_SECRET` | No | - | HMAC-SHA256 signing key for webhook |
| `BARK_URL` | No | - | Bark iOS push URL (e.g. `https://api.day.app/KEY`) |
| `BARK_GROUP` | No | `Argos` | Bark notification group name |
| `TELEGRAM_BOT_TOKEN` | No | - | Telegram bot token |
| `TELEGRAM_CHAT_ID` | No | - | Telegram chat/group ID to send messages to |

## Board Source Types

Each board has a `source_type` that determines how content is fetched:

| Source Type | Description | Example `source_config` |
|-------------|-------------|------------------------|
| `rss` | Pull from RSS feeds | `{"feeds": ["https://hnrss.org/frontpage"]}` |
| `hackernews` | Fetch HN top stories + comments | `{"fetch_top_stories": 30, "min_score": 100}` |
| `reddit` | Fetch Reddit subreddit/user posts | `{"subreddits": [{"subreddit": "LocalLLaMA"}], "fetch_comments": 5}` |
| `github` | Fetch GitHub user events & repo releases | `{"users": ["openai"], "repos": [{"owner": "openai", "repo": "whisper"}]}` |
| `multi` | Combine multiple source types in parallel | `{"sources": {"rss": {"feeds": [...]}, "hackernews": {"min_score": 50}}}` |
| `pure_llm` | LLM generates original content (no external data) | `{"items_per_day": 5, "style": "fun facts"}` |

## MCP Server (AI Agent Integration)

Argos exposes its capabilities as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, allowing AI assistants like Claude, Cursor, and Windsurf to directly query your briefings, ask RAG questions, and manage preferences.

> ⚠️ **SQLite limitation**: Do NOT run the MCP Server alongside the FastAPI web server when using the default SQLite database. Both processes share the same SQLite file, and concurrent writes may cause `database is locked` errors or data corruption. Stop the web server first, or switch to PostgreSQL for concurrent access.

### Available Tools

| Tool | Description |
|------|-------------|
| `get_daily_summary` | Read today's briefing for a board |
| `generate_summary` | Trigger summary generation |
| `ask_article` | RAG Q&A about any ingested article |
| `ask_global` | Cross-article RAG Q&A across all ingested content |
| `search_news` | Keyword search across news history |
| `list_boards` | List all content boards |
| `add_feedback` | Like/dislike articles for personalization |
| `get_user_interests` | View current persona/preferences |
| `get_system_status` | System health and config info |
| `deep_research` | Decompose a question into sub-queries and synthesize a structured report |
| `get_weekly_report` | Generate a structured weekly report with themes and editorial |
| `get_topic_tree` | Get a hierarchical topic tree from article topic paths |
| `get_trending_topics` | Find topics trending upward over a time period |
| `get_cost_breakdown` | Per-label LLM token usage breakdown for cost tracking |

### Usage

```bash
# stdio transport (for IDE integrations like Cursor/Windsurf)
python mcp_server.py

# Or add to your MCP client config (e.g. claude_desktop_config.json):
{
  "mcpServers": {
    "argos": {
      "command": "python",
      "args": ["path/to/Argos/mcp_server.py"]
    }
  }
}
```

## Architecture

The service layer uses a **facade pattern** to keep imports backward-compatible while allowing large modules to be split internally:

### Service Facades

| Facade | Location | Exports |
|--------|----------|--------|
| `llm_service.py` | `app/services/llm/` | `LLMService`, `llm_service` |
| `rag_service.py` | `app/services/rag/_core.py` | All public RAG functions |
| `db_service.py` | `app/services/repositories/` | `DBService`, `db_service` |

### Internal Structure

- **LLM Service**: `ScoringMixin`, `SummaryMixin`, `WeeklyMixin`, `WizardMixin` + `LLMClient` with CircuitBreaker and multi-tier routing
- **RAG Service**: Hybrid retrieval pipeline (Bi-Encoder + BM25 + Cross-Encoder reranking), HyDE rewriting, background ingestion, cross-article search
- **DB Service**: `SummaryRepo`, `PersonaRepo`, `BoardRepo`
- **Notification**: `dispatcher.py` + `channels.py` — multi-channel dispatcher (email, webhook, Bark, Telegram)
- **Source Adapters**: Pluggable adapters for `rss`, `hackernews`, `reddit`, `github`, `multi`, `pure_llm`

### Standalone Services

| Service | Description |
|---------|-------------|
| `filtering_service.py` | Rule-based content quality filtering (blacklist keywords + heuristics) |
| `clustering_service.py` | Event grouping engine (Bi-Encoder + Jaccard fallback) |
| `insights_service.py` | Topic tree, trending topics, heatmap, entity timeline |
| `research_service.py` | Deep research cycle (decompose → search → synthesize) |
| `memory_service.py` | User factual memory CRUD for prompt enrichment |
| `interest_filter.py` | Persona-based interest pre-filtering before scoring |
| `dedup_service.py` | URL normalization + AI semantic deduplication |
| `learning_service.py` | Feedback-driven interest extraction and reranking |
| `source_health_service.py` | RSS/API source health monitoring and logging |
| `redis_service.py` | Redis cache wrapper |
| `metrics_service.py` | LLM token usage and latency tracking |
| `chat_history_service.py` | Per-article chat history persistence |
| `rss_service.py` | RSS feed fetching and parsing |
| `email_service.py` | Email push via SMTP |

> **Note**: New code should import from concrete subpackages (e.g., `from app.services.llm import LLMService`) rather than facades.

## Project Structure

```text
.
├── app/
│   ├── api/                    # FastAPI routes (main + RAG)
│   ├── core/                   # Config, DB, HTTP client, scheduler, auth, logging, URL safety
│   ├── models/                 # SQLModel domain + Pydantic schemas + source config validation
│   ├── prompts/                # LLM prompt templates (daily_briefing, quality_scoring, etc.)
│   ├── scrapers/               # HN / Reddit / GitHub scrapers
│   ├── services/
│   │   ├── source_adapters/    # Pluggable board source adapters
│   │   ├── llm/                # LLM client, scoring, summary, weekly, wizard
│   │   ├── rag/                # RAG pipeline (bi-encoder, cross-encoder, ChromaDB, BM25)
│   │   ├── repositories/      # Database repositories (summary, persona, board)
│   │   ├── notification/      # Multi-channel dispatcher (email, webhook, bark, telegram)
│   │   ├── chat_history_service.py
│   │   ├── clustering_service.py
│   │   ├── dedup_service.py
│   │   ├── email_service.py
│   │   ├── filtering_service.py
│   │   ├── insights_service.py
│   │   ├── interest_filter.py
│   │   ├── learning_service.py
│   │   ├── memory_service.py
│   │   ├── metrics_service.py
│   │   ├── redis_service.py
│   │   ├── research_service.py
│   │   ├── rss_service.py
│   │   └── source_health_service.py
│   ├── skills/                 # Extensible skill plugins
│   └── web/                    # Jinja templates + static assets
├── alembic/                    # Database migrations
├── data/
│   ├── chroma/                 # Local vector store
│   └── sqlite/                 # Local SQLite database
├── logs/                      # Runtime logs
├── scripts/                   # Launcher scripts + Redis bootstrap + model download
├── tests/                     # Pytest test suite
└── tools/                     # Bundled tools (Redis, etc.)
```

## Key Files

| Path | Description |
|------|-------------|
| `main.py` | Application entry point (FastAPI lifespan, middleware, routes) |
| `mcp_server.py` | MCP Server entry point (14 tools for AI assistant integration) |
| `app/core/config.py` | Pydantic Settings with all env vars and defaults |
| `app/core/db.py` | Async SQLAlchemy engine, session factory, migrations, seeding |
| `app/core/scheduler.py` | APScheduler background jobs with TaskRun tracking |
| `app/models/domain.py` | SQLModel tables (Board, NewsItem, DailySummary, UserPersona, UserMemory, Source, TaskRun, etc.) |
| `app/models/schemas.py` | Pydantic request/response schemas with LLM output tolerance |
| `app/models/source_configs.py` | Per-source-type Pydantic validation for board `source_config` |
| `app/prompts/` | LLM prompt templates (daily_briefing, quality_scoring, weekly_*, etc.) |
| `app/web/static/` | Frontend static assets |
| `app/web/templates/` | Jinja2 HTML templates |
| `data/sqlite/argos.db` | SQLite database |
| `data/chroma/` | ChromaDB vector store |
| `scripts/Open_Web_Dashboard.bat` | Windows one-click launcher |
| `scripts/start.sh` | macOS / Linux one-click launcher |
| `scripts/download_models.py` | Pre-download RAG embedding models |

## Tech Stack

- **Backend**: FastAPI, SQLModel, APScheduler, Alembic
- **LLM**: Any OpenAI-compatible API via configurable `LLMClient` with CircuitBreaker (DeepSeek, OpenAI, Groq, etc.)
- **RAG**: Sentence Transformers, ChromaDB, BM25, Cross-Encoder reranking, HyDE
- **MCP**: FastMCP, Model Context Protocol
- **Database**: SQLite (async via aiosqlite), Redis (cache)
- **Scraping**: httpx, feedparser, BeautifulSoup, trafilatura
- **Logging**: structlog (structured JSON logging)
- **Templating**: Jinja2 (HTML + LLM prompts)

## API Reference

All endpoints are prefixed with `/api/v1`. When `API_KEY` is set, requests must include the `X-API-Key` header.

### Briefing & Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/summary` | Get or generate daily summary (with caching) |
| GET | `/briefing` | Structured briefing with sections + clusters |
| POST | `/briefing/refine` | Refine existing briefing with instruction |
| GET | `/briefing/refine/{session_id}` | Check refinement session status |
| GET | `/history` | Summary history archive |
| GET | `/history/weekly_insight` | AI-generated weekly insight |
| GET | `/history/weekly_report` | Structured weekly report |

### Boards

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/boards` | List all boards |
| POST | `/boards` | Create a new board |
| GET | `/boards/{slug}` | Get board details |
| PATCH | `/boards/{slug}` | Update board settings |
| DELETE | `/boards/{slug}` | Soft-delete a board |
| GET | `/boards/{slug}/perspectives` | List available perspectives |
| POST | `/boards/wizard` | AI-guided board wizard |

### Persona & Preferences

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/persona` | List persona instructions |
| POST | `/persona` | Add persona instruction |
| DELETE | `/persona/{id}` | Delete persona instruction |
| GET | `/persona/inferred` | AI-inferred interests from feedback |
| GET | `/preferences` | Explicit preferences (persona + memory) |

### Feedback

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/feedback/interest-options` | Get LLM-suggested interest options for a liked article |
| POST | `/feedback/save-reason` | Save interest reason from feedback |

### RAG

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/rag/ingest` | Ingest a URL into the vector store |
| GET | `/rag/ingest_status` | Check background ingestion status |
| POST | `/rag/overview` | Generate article overview |
| POST | `/rag/query` | RAG Q&A (SSE streaming) |
| POST | `/rag/query/global` | Cross-article RAG Q&A (SSE streaming) |
| GET | `/rag/history` | Chat history for an article |
| POST | `/rag/feedback` | Record like/dislike feedback |

### Insights & Research

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/insights/heatmap` | Category frequency heatmap |
| GET | `/insights/timeline` | Entity occurrence timeline |
| GET | `/insights/topic_tree` | Hierarchical topic tree |
| GET | `/insights/trending` | Trending topics analysis |
| POST | `/research` | Deep research cycle |

### Admin & Monitoring

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ping` | Health check |
| GET | `/metrics` | System metrics (token usage, latency) |
| GET | `/metrics/cost` | Per-label LLM cost breakdown |
| GET | `/admin/tasks` | Background task run history |
| GET | `/admin/sources/health` | Source health dashboard |
| GET | `/admin/sources/{id}/health_log` | Source health log entries |
| GET | `/feeds` | Manually fetch all RSS feeds |
| POST | `/sources/test` | Test a single RSS feed URL |
| GET | `/feed` | RSS 2.0 XML feed export |

### Public Pages

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard (HTML) |
| GET | `/feed` | Public SEO-friendly feed page (no auth) |

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


