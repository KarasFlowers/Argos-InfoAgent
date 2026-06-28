# Argos

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com)

**[English](README.md) | [Chinese](README_zh.md)**

> Understand the tech trends you care about in 10 minutes a day - AI daily briefings plus a reading assistant.

Argos is a FastAPI-based daily tech briefing and reading assistant. It aggregates content from RSS, Hacker News, Reddit, GitHub, or pure LLM boards, uses any OpenAI-compatible LLM to curate structured summaries, and supports recommendation explanations, article-level RAG chat, and feedback-driven personalization.

Each board runs independently with its own sources, prompt, persona, schedule, and notification settings.

## What It Does

- **Daily briefing flow**: read today's briefing, understand why each story was recommended, ask follow-up questions, save useful items, and give feedback.
- **Reading assistant**: article-level RAG chat with cited evidence, fast overviews, suggested questions, hybrid retrieval, Cross-Encoder reranking, and HyDE query rewriting.
- **Personalization**: explicit like/dislike feedback, focus and block topics, source preferences, and persistent user memory.
- **Board system**: custom boards for different topics, sources, prompts, personas, schedules, and notification channels.
- **Notifications**: scheduled or on-demand SMTP email delivery. External notifications are disabled by default; currently `NOTIFY_CHANNELS=email` is the implemented channel.
- **Advanced tools**: deep research, cross-article RAG, MCP Server, source health monitoring, cost metrics, filtering, clustering, and weekly insights.

The web dashboard runs at `http://127.0.0.1:8000`. A public SEO-friendly feed page is available at `/feed`.

## Quick Start

### Prerequisites

- Python 3.11+
- Docker, or Python for local startup
- An OpenAI-compatible LLM API key

### Docker Lite

```bash
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

cp .env.template .env
# Edit .env and set LLM_API_KEY.
# LLM_BASE_URL is required when using generic `LLM_API_KEY`;
# legacy DEEPSEEK_BASE_URL is used only when LLM_API_KEY is unset.

docker compose up -d
```

Open `http://127.0.0.1:8000`.

The default Compose stack is lightweight: it starts only the web app, keeps `RAG_ENABLED=false`, does not pre-download embedding models, and does not require Redis.

### Deployment Profiles

| Profile | Command | What it enables |
|---------|---------|-----------------|
| Lite | `docker compose up -d` | Daily briefings, personalization, saved items, and basic reading flow. |
| Lite + Redis | `docker compose -f docker-compose.yml -f docker-compose.redis.yml up -d` | Lite plus Redis-backed cache and metrics. |
| Full RAG | `docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d --build` | Article-level RAG, ChromaDB, embedding/rerank dependencies, and persistent model cache. |
| Full RAG + Redis | `docker compose -f docker-compose.yml -f docker-compose.rag.yml -f docker-compose.redis.yml up -d --build` | Full local reading assistant plus Redis cache. |

Set `PREWARM_RAG_MODELS=true` with the RAG profile only when you want the image build to download models up front. Otherwise models are downloaded lazily on first RAG use and cached under `data/hf-cache`.

Optional checks:

```bash
python scripts/docker_smoke.py --no-build
python scripts/runtime_smoke.py
```

### One-Click Local Start

```bash
# macOS / Linux
chmod +x scripts/start.sh
./scripts/start.sh

# Windows
scripts\Open_Web_Dashboard.bat
```

The launcher creates a virtual environment, installs lightweight dependencies, helps create `.env`, optionally checks Redis, installs/downloads RAG dependencies only when `RAG_ENABLED=true`, starts the backend, and opens the dashboard.

### Manual Local Setup

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.template .env
# Edit .env and set LLM_API_KEY.

# Optional: install only when RAG_ENABLED=true
pip install -r requirements-rag.txt
pip install -r requirements-mcp.txt  # only when running mcp_server.py
python scripts/download_models.py

uvicorn main:app --reload
```

## Essential Configuration

| Variable | Required | Notes |
|----------|----------|-------|
| `LLM_API_KEY` | Yes | API key for any OpenAI-compatible provider. |
| `LLM_BASE_URL` | Usually | Required when using generic `LLM_API_KEY`; legacy `DEEPSEEK_BASE_URL` is used only when `LLM_API_KEY` is unset. |
| `LLM_MODEL` | No | Defaults to `deepseek-chat`. |
| `API_KEY` | No | When set, private API routes require `X-API-Key`. |
| `PUBLIC_BASE_URL` | No | Public origin used in RSS/canonical links. |
| `REDIS_URL` | No | Optional Redis cache URL. Docker Lite runs without Redis. |
| `RAG_ENABLED` | No | Defaults to `false`; set `true` for article-level RAG. |
| `CORS_ORIGINS` | No | Comma-separated browser origins. Use origins only; `*` disables credentialed CORS. |
| `NOTIFY_CHANNELS` | No | Empty disables scheduled external notifications; use `email` for SMTP delivery. |

See [.env.template](.env.template) for the full list.

## Security Notes

Argos is a private single-user/self-hosted app by default. It does not implement multi-tenant accounts or role-based access control.

When `API_KEY` is set, private API requests must include `X-API-Key: <value>`. Public paths remain open: `/`, `/favicon.ico`, `/static/*`, `/feed`, and `/api/v1/ping`. `OPTIONS` requests remain open for CORS preflight. The private `/api/v1/status` endpoint reports readiness and feature flags without returning provider keys, tokens, or passwords.

Read [SECURITY.md](SECURITY.md) before exposing Argos outside localhost or a private network.

## More Documentation

- [Project reference](docs/PROJECT_REFERENCE.md): full feature list, board source types, MCP usage, architecture, project structure, API map, and operation notes.
- [Development guide](DEVELOPMENT.md): local development, tests, migrations, and release checks.
- [Contributing guide](CONTRIBUTING.md): branch strategy, commit style, and PR workflow.
- [Industrialization audit](docs/INDUSTRIALIZATION_AUDIT.md): release-hardening evidence.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and run the release gate before opening a PR:

```bash
python scripts/check_release.py
```

## License

Argos is licensed under the MIT License. See [LICENSE](LICENSE).
