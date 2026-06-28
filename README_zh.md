# Argos

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com)

**[English](README.md) | [Chinese](README_zh.md)**

> 每天 10 分钟理解你关心的技术趋势 - AI 每日简报 + 阅读助手

Argos 是一个基于 FastAPI 的每日科技简报与阅读助手。它从 RSS、Hacker News、Reddit、GitHub 或纯 LLM 看板聚合内容，使用任意 OpenAI 兼容 LLM 策划结构化摘要，并支持推荐解释、文章级 RAG 追问和反馈驱动的个性化偏好。

每个看板独立运行，拥有自己的来源、提示词、角色、调度和通知设置。

## 核心功能

- **每日简报主路径**：阅读今日简报，理解每条资讯的推荐原因，继续追问，收藏有价值内容，并通过反馈让系统学习偏好。
- **阅读助手**：文章级 RAG 对话，支持引用依据、快速导读、建议追问、混合检索、Cross-Encoder 重排序和 HyDE 查询重写。
- **个性化推荐**：显式喜欢/不喜欢反馈、关注/屏蔽话题、来源偏好和持久化用户记忆。
- **看板系统**：为不同主题创建独立看板，分别配置来源、提示词、角色、调度和通知渠道。
- **通知推送**：通过 SMTP 邮件定时或按需推送。外部通知默认关闭；当前已实现的渠道是 `NOTIFY_CHANNELS=email`。
- **进阶能力**：深度研究、跨文章 RAG、MCP Server、来源健康监控、成本统计、过滤、聚类和周度洞察。

Web 仪表板运行在 `http://127.0.0.1:8000`。公开的 SEO 友好订阅页面位于 `/feed`。

## 快速开始

### 环境要求

- Python 3.11+
- Docker，或用于本地启动的 Python
- 任意 OpenAI 兼容 LLM API Key

### Docker Lite

```bash
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

cp .env.template .env
# 编辑 .env 并设置 LLM_API_KEY。
# 使用通用 `LLM_API_KEY` 时需要显式设置 LLM_BASE_URL；
# 旧版 DEEPSEEK_BASE_URL 只有在未设置 LLM_API_KEY 时才会回退使用。

docker compose up -d
```

打开 `http://127.0.0.1:8000`。

默认 Compose 栈是轻量档：只启动 Web 应用，保持 `RAG_ENABLED=false`，不预下载 embedding 模型，也不强制依赖 Redis。

### 部署档位

| 档位 | 命令 | 启用能力 |
|------|------|----------|
| Lite | `docker compose up -d` | 每日简报、个性化、收藏和基础阅读流程。 |
| Lite + Redis | `docker compose -f docker-compose.yml -f docker-compose.redis.yml up -d` | Lite 加 Redis 缓存和指标。 |
| Full RAG | `docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d --build` | 文章级 RAG、ChromaDB、embedding/rerank 依赖和持久化模型缓存。 |
| Full RAG + Redis | `docker compose -f docker-compose.yml -f docker-compose.rag.yml -f docker-compose.redis.yml up -d --build` | 完整本地阅读助手加 Redis 缓存。 |

只有在使用 RAG 档且希望构建镜像时提前下载模型，才设置 `PREWARM_RAG_MODELS=true`。否则模型会在首次使用 RAG 时按需下载，并缓存到 `data/hf-cache`。

可选检查：

```bash
python scripts/docker_smoke.py --no-build
python scripts/runtime_smoke.py
```

### 本地一键启动

```bash
# macOS / Linux
chmod +x scripts/start.sh
./scripts/start.sh

# Windows
scripts\Open_Web_Dashboard.bat
```

启动器会创建虚拟环境、安装轻量依赖、引导创建 `.env`、可选检查 Redis，并且只在 `RAG_ENABLED=true` 时安装/下载 RAG 依赖，然后启动后端并打开仪表板。

### 手动本地部署

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.template .env
# 编辑 .env 并设置 LLM_API_KEY。

# 仅在 RAG_ENABLED=true 时需要
pip install -r requirements-rag.txt
pip install -r requirements-mcp.txt  # 仅运行 mcp_server.py 时需要
python scripts/download_models.py

uvicorn main:app --reload
```

## 必要配置

| 变量 | 必需 | 说明 |
|------|------|------|
| `LLM_API_KEY` | 是 | 任意 OpenAI 兼容供应商的 API Key。 |
| `LLM_BASE_URL` | 通常需要 | 使用通用 `LLM_API_KEY` 时需要显式设置；旧版 `DEEPSEEK_BASE_URL` 只有在未设置 `LLM_API_KEY` 时才会回退使用。 |
| `LLM_MODEL` | 否 | 默认值为 `deepseek-chat`。 |
| `API_KEY` | 否 | 设置后，私有 API 路由需要 `X-API-Key`。 |
| `PUBLIC_BASE_URL` | 否 | 生成 RSS/canonical 链接时使用的公开访问地址。 |
| `REDIS_URL` | 否 | 可选 Redis 缓存地址。Docker Lite 不需要 Redis。 |
| `RAG_ENABLED` | 否 | 默认 `false`；设为 `true` 后启用文章级 RAG。 |
| `CORS_ORIGINS` | 否 | 逗号分隔的浏览器来源。只填写 origin；设置为 `*` 时会禁用 credentialed CORS。 |
| `NOTIFY_CHANNELS` | 否 | 留空则禁用定时外部通知；SMTP 邮件使用 `email`。 |

完整配置见 [.env.template](.env.template)。

## 安全说明

Argos 默认定位为私有单用户/自托管应用，不包含多租户账号体系或角色权限模型。

设置 `API_KEY` 后，私有 API 请求必须携带 `X-API-Key: <value>`。公开路径保持开放：`/`、`/favicon.ico`、`/static/*`、`/feed` 和 `/api/v1/ping`。`OPTIONS` 请求会继续开放，用于 CORS 预检。私有 `/api/v1/status` 端点只返回就绪状态和功能开关，不返回供应商密钥、token 或密码。

如果要把 Argos 暴露到 localhost 或私有网络之外，请先阅读 [SECURITY.md](SECURITY.md)。

## 更多文档

- [项目参考文档](docs/PROJECT_REFERENCE.md)：完整功能列表、看板来源类型、MCP 用法、架构、项目结构、API 地图和运维说明。
- [开发指南](DEVELOPMENT.md)：本地开发、测试、迁移和发布检查。
- [贡献指南](CONTRIBUTING.md)：分支策略、提交格式和 PR 流程。
- [工业化加固记录](docs/INDUSTRIALIZATION_AUDIT.md)：发布加固证据。

## 贡献

欢迎贡献代码。提交 PR 前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并运行发布门禁：

```bash
python scripts/check_release.py
```

## 许可证

Argos 使用 MIT 许可证。详情见 [LICENSE](LICENSE)。
