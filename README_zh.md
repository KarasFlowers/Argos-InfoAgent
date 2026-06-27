# Argos

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com)

**[English](README.md) | [Chinese](README_zh.md)**

> AI + RAG = 1+1>2 — 多看板管理、文章级 RAG 问答、深度研究、MCP 集成

Argos 是一个基于 FastAPI 的每日科技简报应用。它从多种来源（RSS、Hacker News、Reddit、GitHub 或纯 LLM）聚合内容，使用任意 OpenAI 兼容 LLM 策划结构化摘要，并提供文章级 RAG 对话与反馈驱动的个性化推荐。每个看板独立运行，拥有自己的来源、提示词、角色和推送渠道。

## ✨ 亮点特性

### 🧩 看板系统

创建自定义分区（看板）—— 每个看板拥有独立的来源类型、系统提示词、角色设定、调度和通知渠道。AI 引导的**看板向导**帮你秒级配置新看板。

### 🔍 文章级 RAG

混合检索管道，结合 Bi-Encoder + BM25 与 **Cross-Encoder 重排序**和 **HyDE 查询重写**。支持单篇和**跨文章**问答，覆盖所有已入库内容。

### 🔬 深度研究

将复杂问题分解为子查询，搜索 RAG + 网络来源，合成结构化研究报告 —— 一键完成。

### 🤖 MCP Server

通过 [Model Context Protocol](https://modelcontextprotocol.io/) 将全部能力暴露给 Claude、Cursor、Windsurf 等 AI 助手 —— 14 个工具覆盖简报、RAG、研究和偏好管理。

### 🎯 个性化推荐

显式喜欢/不喜欢反馈 + 自动兴趣提取 + **用户记忆系统**（持久化偏好和上下文）。越用越懂你。

### 📢 邮件推送

通过 **SMTP 邮件** 推送每日简报 —— 定时自动送达或按需触发。外部通知默认关闭。

---

## 更多功能

- **多源聚合** — RSS、Hacker News、Reddit、GitHub 或纯 LLM 生成内容
- **多模型 LLM 路由** — 分离的「快速」和「智能」层级，配合 CircuitBreaker 实现弹性调用
- **LLM 驱动的每日简报** — 包含分类、要点、标签和主题路径的结构化摘要
- **每日简报精炼** — 使用自然语言指令迭代优化已有简报
- **周报与洞察** — 主题树、趋势分析、热力图、实体时间线和编辑式周报
- **内容聚类** — Bi-Encoder + Jaccard 回退，将相关文章分组为事件
- **规则过滤** — 黑名单关键词/模式，支持管理员审核和恢复工作流
- **来源健康监控** — 跟踪 RSS/API 来源的健康状态和错误日志
- **跨源去重** — URL 规范化 + AI 语义去重
- **URL 安全验证** — 阻止私有/内部 URL，防止 SSRF 攻击
- **本地持久化** — SQLite、ChromaDB 和 Redis 缓存，支持离线优先设计

## 演示

Argos 提供 Web 仪表板（`http://127.0.0.1:8000`），用于浏览每日简报、通过 RAG 与文章对话、管理看板和跟踪洞察。公开的 SEO 友好订阅页面位于 `/feed`。

## 快速开始

### 环境要求

- Python 3.11+
- [Redis](https://redis.io/)（用于缓存）
- 任意 OpenAI 兼容 LLM API Key（如 [DeepSeek](https://platform.deepseek.com/)、OpenAI 等）

### Docker（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. 配置环境变量
cp .env.template .env
# 编辑 .env，设置 LLM_API_KEY（或兼容的 DEEPSEEK_API_KEY）

# 3. 启动服务栈
docker compose up -d

# 可选：运行生产 smoke 验收（健康检查 + API Key 行为）
python scripts/docker_smoke.py --no-build

# 可选：运行非 Docker 本地运行时 smoke
python scripts/runtime_smoke.py

# 4. 浏览器访问
# 打开 http://127.0.0.1:8000
```

Compose 服务栈通过可选的 `env_file` 读取 `.env`，只发布 Argos Web 端口；Redis 保持在 Docker 内部网络中。

### 一键启动（本地推荐）

项目自带启动脚本，自动处理 **虚拟环境创建、依赖安装、.env 配置、Redis 启动、模型下载、打开浏览器** 全流程：

```bash
# macOS / Linux
chmod +x scripts/start.sh
./scripts/start.sh

# Windows — 双击或运行：
scripts\Open_Web_Dashboard.bat
```

首次运行时脚本会自动：
1. 创建虚拟环境并安装依赖
2. 引导你输入 LLM API Key（自动生成 `.env`）
3. 检查/启动 Redis
4. 预下载 RAG 嵌入模型（~650 MB，仅首次）
5. 启动后端并在浏览器中打开仪表板

### 手动部署

<details>
<summary>点击展开详细步骤</summary>

```bash
# 1. 克隆仓库
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. 创建并激活虚拟环境
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.template .env
# 编辑 .env，设置 LLM_API_KEY（或兼容的 DEEPSEEK_API_KEY）

# 5.（可选）预下载 RAG 模型，避免首次请求延迟
python scripts/download_models.py

# 6. 启动 Redis（如未运行）
# Windows：.bat 启动器会自动处理
# Linux / macOS：redis-server --daemonize yes

# 7. 启动应用
uvicorn main:app --reload

# 8. 浏览器打开 http://127.0.0.1:8000
```

</details>

## 配置

复制 `.env.template` 为 `.env` 并配置你的设置。至少需要设置 `LLM_API_KEY`（或旧版 `DEEPSEEK_API_KEY`）。

### 环境变量

| 变量 | 必需 | 默认值 | 描述 |
|------|------|--------|------|
| `LLM_API_KEY` | **是** | - | 任意 OpenAI 兼容 LLM 提供商的 API 密钥 |
| `LLM_MODEL` | 否 | `deepseek-chat` | 所有 LLM 调用使用的默认模型名 |
| `LLM_BASE_URL` | 否 | - | LLM API 的基础 URL。使用通用 `LLM_API_KEY` 时需要显式设置；只有未设置 `LLM_API_KEY` 时才会回退到旧版 `DEEPSEEK_BASE_URL` |
| `LLM_TIMEOUT` | 否 | `180` | 请求超时（秒） |
| `LLM_MAX_RETRIES` | 否 | `1` | 瞬态失败最大重试次数 |
| `FAST_LLM` | 否 | - | 「快速」层级模型，`provider:model` 格式（如 `openai:gpt-4o-mini`）。留空则回退到 `LLM_MODEL` |
| `SMART_LLM` | 否 | - | 「智能」层级模型，`provider:model` 格式。留空则回退到 `LLM_MODEL` |
| `DEEPSEEK_API_KEY` | 否 | - | 旧版别名 — 当 `LLM_API_KEY` 未设置时作为回退 |
| `API_KEY` | 否 | - | 私有 API 认证密钥，通过 `X-API-Key` 请求头传递。不设置则无需认证 |
| `PUBLIC_BASE_URL` | 否 | `http://localhost:8000` | 生成 RSS/canonical 链接时使用的公开访问地址。必须是绝对 `http(s)` URL，不能包含 query/fragment |
| `SQLALCHEMY_DATABASE_URI` | 否 | `sqlite+aiosqlite:///./data/sqlite/argos.db` | 异步 SQLite 数据库路径 |
| `CHROMA_DB_DIR` | 否 | `./data/chroma` | ChromaDB 持久化存储路径 |
| `REDIS_URL` | 否 | `redis://localhost:6379` | Redis 连接 URL |
| `RAG_BACKGROUND_INGEST_ENABLED` | 否 | `True` | 启用后台 RAG 入库管道 |
| `RAG_BACKGROUND_INGEST_WORKERS` | 否 | `2` | 后台入库工作协程数量 |
| `RAG_HYDE_ENABLED` | 否 | `True` | 启用 HyDE（假设文档嵌入）查询重写 |
| `HISTORY_DAYS_TO_KEEP` | 否 | `7` | 历史数据保留天数 |
| `CORS_ORIGINS` | 否 | `http://localhost:3000,...` | 逗号分隔的前端允许来源。每一项必须是 origin，不能带路径；使用 `*` 时会关闭 credentialed CORS |
| `CORS_ALLOW_CREDENTIALS` | 否 | `True` | 对明确列出的来源允许 credentialed CORS。`CORS_ORIGINS=*` 时该设置会被忽略 |
| `GITHUB_TOKEN` | 否 | - | GitHub 个人访问令牌（将速率限制提升至 5000 次/小时） |
| `HN_FETCH_TOP_STORIES` | 否 | `30` | 获取的 Hacker News 热门故事数量 |
| `HN_MIN_SCORE` | 否 | `100` | Hacker News 最低分数阈值 |
| `REDDIT_FETCH_COMMENTS` | 否 | `5` | 每个 Reddit 帖子包含的热门评论数 |
| `SMTP_HOST` | 否 | - | 邮件推送的 SMTP 服务器 |
| `SMTP_PORT` | 否 | `465` | SMTP 服务器端口 |
| `SMTP_USER` | 否 | - | SMTP 用户名 |
| `SMTP_PASSWORD` | 否 | - | SMTP 密码 |
| `SMTP_FROM` | 否 | - | 发件人地址（如 `Argos <you@example.com>`） |
| `EMAIL_SUBSCRIBERS` | 否 | `[]` | 订阅者邮箱地址的 JSON 列表 |
| `DAILY_PUSH_TIME` | 否 | `08:00` | 每日邮件发送时间（HH:MM 格式） |
| `LOG_FORMAT` | 否 | - | 设置为 `json` 后输出结构化 JSON 日志；常见密钥字段和 token 形态的值会在输出前脱敏 |
| `NOTIFY_CHANNELS` | 否 | - | 通知渠道（逗号分隔）。留空则禁用定时外部通知；当前仅实现 `email` |

### 安全与自托管说明

- Argos 默认定位为私有单用户/自托管应用，不包含多租户账号体系或角色权限模型。
- 设置 `API_KEY` 后，私有 API 请求必须携带 `X-API-Key: <value>`。公开路径保持开放：`/`、`/favicon.ico`、`/static/*`、`/feed`、`/api/v1/ping`；`OPTIONS` 请求用于 CORS 预检时也保持开放。
- Web 仪表板提供“密钥”入口，会把 `API_KEY` 保存在浏览器 localStorage，并在同源 API 请求中自动发送 `X-API-Key`。仅建议在可信个人设备上保存。
- `LLM_API_KEY`、`DEEPSEEK_API_KEY` 等供应商密钥从环境变量读取；新安装不会把这些密钥复制进 SQLite 的 `ModelApiConfig` 表。
- 如果通过反向代理对外提供服务，请把 `PUBLIC_BASE_URL` 设置为外部可访问地址，避免 RSS/feed 链接生成错误。
- 使用 `python scripts/backup_data.py` 同时备份 `data/sqlite/argos.db` 和 `data/chroma/`；如果同一时间戳已存在，会自动生成带后缀的新归档，不会覆盖旧备份。恢复前先停止 Argos，并运行 `python scripts/restore_data.py backups/<archive>.zip --dry-run` 查看将写入的目标路径；只有确认要覆盖已有本地数据时才传入 `--force`。
- 轻量部署可以设置 `RAG_ENABLED=false`，跳过文章级 RAG 和大体积 embedding 模型下载。
- 定时外部通知默认关闭。启用邮件推送前，请显式设置 `NOTIFY_CHANNELS=email` 和 SMTP 配置。
- 在把 Argos 暴露到 localhost 或私有网络之外前，请阅读 [SECURITY.md](SECURITY.md)。
- 工业化加固证据见 [docs/INDUSTRIALIZATION_AUDIT.md](docs/INDUSTRIALIZATION_AUDIT.md)。

## 看板来源类型

每个看板都有一个 `source_type`，决定了内容的获取方式：

| 来源类型 | 描述 | 示例 `source_config` |
|----------|------|----------------------|
| `rss` | 从 RSS 订阅源拉取 | `{"feeds": ["https://hnrss.org/frontpage"]}` |
| `hackernews` | 获取 HN 热门故事和评论 | `{"fetch_top_stories": 30, "min_score": 100}` |
| `reddit` | 获取 Reddit 子版块/用户帖子 | `{"subreddits": [{"subreddit": "LocalLLaMA"}], "fetch_comments": 5}` |
| `github` | 获取 GitHub 用户事件和仓库发布 | `{"users": ["openai"], "repos": [{"owner": "openai", "repo": "whisper"}]}` |
| `multi` | 并行组合多种来源类型 | `{"sources": {"rss": {"feeds": [...]}, "hackernews": {"min_score": 50}}}` |
| `pure_llm` | LLM 生成原创内容（无外部数据） | `{"items_per_day": 5, "style": "fun facts"}` |

## MCP Server（AI 助手集成）

Argos 通过 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 协议暴露核心能力，让 Claude、Cursor、Windsurf 等 AI 助手可以直接查询简报、提问文章、管理偏好。

> ⚠️ **SQLite 限制**：使用默认 SQLite 数据库时，**不要**同时运行 MCP Server 和 FastAPI Web 服务器。两个进程共享同一 SQLite 文件，并发写入可能导致 `database is locked` 错误或数据损坏。请先停止 Web 服务器，或切换到 PostgreSQL 以支持并发访问。

### 可用工具

| 工具 | 描述 |
|------|------|
| `get_daily_summary` | 获取指定看板的每日简报 |
| `generate_summary` | 触发简报生成 |
| `ask_article` | 基于 RAG 的文章问答 |
| `ask_global` | 跨文章 RAG 问答，搜索所有已入库内容 |
| `search_news` | 关键词搜索历史新闻 |
| `list_boards` | 列出所有看板 |
| `add_feedback` | 点赞/踩文章以个性化推荐 |
| `get_user_interests` | 查看当前兴趣/偏好 |
| `get_system_status` | 系统健康状态 |
| `deep_research` | 将问题分解为子查询并合成结构化报告 |
| `get_weekly_report` | 生成包含主题和编辑评论的结构化周报 |
| `get_topic_tree` | 从文章主题路径获取层级主题树 |
| `get_trending_topics` | 发现一段时间内上升趋势的主题 |
| `get_cost_breakdown` | 按标签的 LLM Token 用量明细，用于成本追踪 |

### 使用方式

```bash
# stdio 传输（适用于 Cursor/Windsurf 等 IDE 集成）
python mcp_server.py

# 或添加到 MCP 客户端配置（如 claude_desktop_config.json）：
{
  "mcpServers": {
    "argos": {
      "command": "python",
      "args": ["path/to/Argos/mcp_server.py"]
    }
  }
}
```

## 架构设计

服务层采用**外观模式（Facade Pattern）**，保持导入向后兼容的同时，允许大型模块在内部拆分：

### 服务外观

| 外观 | 位置 | 导出内容 |
|------|------|----------|
| `llm_service.py` | `app/services/llm/` | `LLMService`, `llm_service` |
| `rag_service.py` | `app/services/rag/_core.py` | 所有公共 RAG 函数 |
| `db_service.py` | `app/services/repositories/` | `DBService`, `db_service` |

### 内部结构

- **LLM 服务**：`ScoringMixin`、`SummaryMixin`、`WeeklyMixin`、`WizardMixin` + 带 CircuitBreaker 和多层级路由的 `LLMClient`
- **RAG 服务**：混合检索管道（Bi-Encoder + BM25 + Cross-Encoder 重排序）、HyDE 重写、后台入库、跨文章搜索
- **数据库服务**：`SummaryRepo`、`PersonaRepo`、`BoardRepo`
- **通知服务**：`notification/dispatcher.py` — 邮件分发器；未支持的 channel 会失败关闭
- **来源适配器**：可插拔适配器，支持 `rss`、`hackernews`、`reddit`、`github`、`multi`、`pure_llm`

### 独立服务

| 服务 | 描述 |
|------|------|
| `filtering_service.py` | 基于规则的内容质量过滤（黑名单关键词 + 启发式） |
| `clustering_service.py` | 事件分组引擎（Bi-Encoder + Jaccard 回退） |
| `insights_service.py` | 主题树、趋势主题、热力图、实体时间线 |
| `research_service.py` | 深度研究循环（分解 → 搜索 → 合成） |
| `memory_service.py` | 用户事实记忆 CRUD，用于提示词增强 |
| `interest_filter.py` | 基于角色的兴趣预过滤（评分前） |
| `dedup_service.py` | URL 规范化 + AI 语义去重 |
| `learning_service.py` | 反馈驱动的兴趣提取和重排序 |
| `source_health_service.py` | RSS/API 来源健康监控和日志 |
| `redis_service.py` | Redis 缓存封装 |
| `metrics_service.py` | LLM Token 用量和延迟追踪 |
| `chat_history_service.py` | 每篇文章的聊天历史持久化 |
| `rss_service.py` | RSS 订阅源获取和解析 |
| `email_service.py` | 通过 SMTP 的邮件推送 |

> **注意**：新代码应从具体子包导入（例如 `from app.services.llm import LLMService`），而非从外观导入。

## 项目结构

```text
.
├── app/
│   ├── api/                    # FastAPI 路由（主路由 + RAG）
│   ├── core/                   # 配置、数据库、HTTP 客户端、调度器、认证、日志、URL 安全
│   ├── models/                 # SQLModel 领域模型 + Pydantic 模式 + 来源配置验证
│   ├── prompts/                # LLM 提示词模板（daily_briefing、quality_scoring 等）
│   ├── scrapers/               # HN / Reddit / GitHub 爬虫
│   ├── services/
│   │   ├── source_adapters/    # 可插拔的看板来源适配器
│   │   ├── llm/                # LLM 客户端、评分、摘要、周报、向导
│   │   ├── rag/                # RAG 管道（bi-encoder、cross-encoder、ChromaDB、BM25）
│   │   ├── repositories/      # 数据库仓库（摘要、角色、看板）
│   │   ├── notification/      # 通知分发器（邮件）
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
│   ├── skills/                 # 可扩展技能插件
│   └── web/                    # Jinja 模板 + 静态资源
├── alembic/                    # 数据库迁移
├── data/
│   ├── chroma/                 # 本地向量存储
│   └── sqlite/                 # 本地 SQLite 数据库
├── logs/                      # 运行日志
├── scripts/                   # 启动脚本 + Redis 引导 + 模型下载
├── tests/                     # Pytest 测试套件
└── tools/                     # 打包工具（Redis 等）
```

## 关键文件

| 路径 | 描述 |
|------|------|
| `main.py` | 应用入口（FastAPI 生命周期、中间件、路由） |
| `mcp_server.py` | MCP Server 入口（14 个工具，用于 AI 助手集成） |
| `app/core/config.py` | Pydantic Settings，包含所有环境变量和默认值 |
| `app/core/db.py` | 异步 SQLAlchemy 引擎、会话工厂、迁移、种子数据 |
| `app/core/scheduler.py` | APScheduler 后台任务，带 TaskRun 追踪 |
| `app/models/domain.py` | SQLModel 表（Board、NewsItem、DailySummary、UserPersona、UserMemory、Source、TaskRun 等） |
| `app/models/schemas.py` | Pydantic 请求/响应模式，带 LLM 输出容错 |
| `app/models/source_configs.py` | 每种来源类型的 Pydantic 验证，用于看板 `source_config` |
| `app/prompts/` | LLM 提示词模板（daily_briefing、quality_scoring、weekly_* 等） |
| `app/web/static/` | 前端静态资源 |
| `app/web/templates/` | Jinja2 HTML 模板 |
| `data/sqlite/argos.db` | SQLite 数据库 |
| `data/chroma/` | ChromaDB 向量存储 |
| `scripts/Open_Web_Dashboard.bat` | Windows 一键启动器 |
| `scripts/start.sh` | macOS / Linux 一键启动器 |
| `scripts/download_models.py` | 预下载 RAG 嵌入模型 |

## 技术栈

- **后端**：FastAPI、SQLModel、APScheduler、Alembic
- **LLM**：任意 OpenAI 兼容 API，通过带 CircuitBreaker 的可配置 `LLMClient`（DeepSeek、OpenAI、Groq 等）
- **RAG**：Sentence Transformers、ChromaDB、BM25、Cross-Encoder 重排序、HyDE
- **MCP**：FastMCP、Model Context Protocol
- **数据库**：SQLite（异步 via aiosqlite）、Redis（缓存）
- **爬虫**：httpx、feedparser、BeautifulSoup、trafilatura
- **日志**：structlog（结构化 JSON 日志）
- **模板**：Jinja2（HTML + LLM 提示词）

## API 参考

私有接口前缀为 `/api/v1`；下方表格中的接口默认省略此前缀，除非明确标为公开页面。设置 `API_KEY` 后，私有请求需携带 `X-API-Key` 请求头；`/api/v1/ping` 保持公开用于健康检查，`OPTIONS` 保持开放用于 CORS 预检。

### 简报与摘要

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/summary` | 获取或生成每日摘要（带缓存） |
| GET | `/briefing` | 结构化简报，包含分区和聚类 |
| POST | `/briefing/refine` | 使用指令精炼已有简报 |
| GET | `/briefing/refine/{session_id}` | 查询精炼会话状态 |
| GET | `/history` | 摘要历史归档 |
| GET | `/history/weekly_insight` | AI 生成的周度洞察 |
| GET | `/history/weekly_report` | 结构化周报 |

### 看板

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/boards` | 列出所有看板 |
| POST | `/boards` | 创建新看板 |
| GET | `/boards/{slug}` | 获取看板详情 |
| PATCH | `/boards/{slug}` | 更新看板设置 |
| DELETE | `/boards/{slug}` | 软删除看板 |
| GET | `/boards/{slug}/perspectives` | 列出可用视角 |
| POST | `/boards/wizard` | AI 引导的看板向导 |

### 角色与偏好

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/persona` | 列出角色指令 |
| POST | `/persona` | 添加角色指令 |
| DELETE | `/persona/{id}` | 删除角色指令 |
| GET | `/persona/inferred` | 从反馈中 AI 推断的兴趣 |
| GET | `/preferences` | 显式偏好（角色 + 记忆） |

### 反馈

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/feedback/interest-options` | 获取 LLM 建议的兴趣选项 |
| POST | `/feedback/save-reason` | 保存反馈中的兴趣原因 |

### RAG

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/rag/ingest` | 将 URL 入库到向量存储 |
| GET | `/rag/ingest_status` | 查询后台入库状态 |
| POST | `/rag/overview` | 生成文章概览 |
| POST | `/rag/query` | RAG 问答（SSE 流式） |
| POST | `/rag/query/global` | 跨文章 RAG 问答（SSE 流式） |
| GET | `/rag/history` | 文章聊天历史 |
| POST | `/rag/feedback` | 记录喜欢/不喜欢反馈 |

### 洞察与研究

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/insights/heatmap` | 分类频率热力图 |
| GET | `/insights/timeline` | 实体出现时间线 |
| GET | `/insights/topic_tree` | 层级主题树 |
| GET | `/insights/trending` | 趋势主题分析 |
| POST | `/research` | 深度研究循环 |

### 管理与监控

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/ping` | 健康检查 |
| GET | `/status` | 私有就绪诊断（数据库/功能/认证状态，不返回密钥） |
| GET | `/metrics` | 系统指标（Token 用量、延迟） |
| GET | `/metrics/cost` | 按标签的 LLM 成本明细 |
| GET | `/admin/tasks` | 后台任务运行历史 |
| GET | `/admin/sources/health` | 来源健康仪表板 |
| GET | `/admin/sources/{id}/health_log` | 来源健康日志 |
| GET | `/feeds` | 手动获取所有 RSS 订阅源 |
| POST | `/sources/test` | 测试单个 RSS 订阅源 URL |
| GET | `/feed` | RSS 2.0 XML 订阅源导出 |

### 公开页面

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/` | Web 仪表板（HTML） |
| GET | `/feed` | 公开 SEO 友好订阅页面（无需认证） |

## 贡献指南

欢迎贡献代码！请随时提交 Pull Request。

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交你的修改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 提交一个 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详情请查看 [LICENSE](LICENSE) 文件。
