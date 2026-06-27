# Argos 项目介绍

> 一款基于 LLM 的智能科技资讯聚合与个性化简报系统

---

## 目录

- [项目概述](#项目概述)
- [核心功能](#核心功能)
- [系统架构](#系统架构)
- [技术栈详解](#技术栈详解)
- [核心模块设计](#核心模块设计)
- [Board 源类型](#board-源类型)
- [数据模型](#数据模型)
- [API 接口设计](#api-接口设计)
- [MCP Server 集成](#mcp-server-集成)
- [前端界面](#前端界面)
- [项目亮点](#项目亮点)
- [部署指南](#部署指南)
- [配置说明](#配置说明)
- [未来展望](#未来展望)

---

## 项目概述

### 背景

在信息爆炸的时代，技术人员每天面对海量的科技资讯，如何高效获取有价值的信息成为一个痛点。传统的 RSS 阅读器只是简单聚合，用户仍需花费大量时间筛选和阅读。Argos 应运而生——它不仅聚合资讯，更通过 AI 技术实现智能筛选、结构化摘要和个性化推荐。

### 定位

Argos 是一个**每日科技简报智能聚合系统**，核心价值在于：

1. **智能筛选**：通过 LLM 对海量资讯进行质量评分，过滤低价值内容
2. **结构化输出**：生成包含概览、分类、要点、标签的结构化简报
3. **深度对话**：基于 RAG 技术实现文章级别的智能问答
4. **个性化推荐**：通过用户反馈持续优化内容推荐

### 目标用户

- 忙碌的技术从业者，需要快速了解行业动态
- 计算机科学学生，希望追踪前沿技术发展
- 科技爱好者，追求高质量的信息摄入

---

## 核心功能

### 1. 多源内容聚合

Argos 支持多种内容源类型：

- **RSS 源**：从任意 RSS/Atom feed 抓取内容
- **Hacker News**：获取热门故事和评论
- **Reddit**：抓取指定 subreddit 或用户的帖子
- **GitHub**：跟踪用户动态和仓库发布
- **多源组合**：并行组合多种源类型
- **纯 LLM 生成**：让 LLM 生成原创内容

### 2. Board 系统

每个 Board 是一个独立的内容板块，拥有：

- 独立的源类型和配置
- 自定义 System Prompt
- 个性化 Persona 设置
- Board 创建向导（AI 引导）

### 3. 每日智能简报

系统每天自动生成结构化的每日简报：

- **概览摘要**：2-3 句话概括当日最重要的技术趋势
- **精选新闻**：8-12 条高质量资讯，每条包含：
  - 独立标题
  - 内容分类（AI、硬件、软件、安全等）
  - 3-5 个关键要点
  - 自动生成的标签
  - 原文链接和来源
- **来源统计**：可视化展示各信息源的贡献度

### 4. 文章深度追问

针对每篇新闻，用户可以点击「深度追问」进入 RAG 对话模式：

- 系统自动抓取并解析原文内容
- 基于向量检索实现精准的上下文定位
- 支持多轮对话，深入探讨文章细节
- 流式输出，实时展示 AI 思考过程

### 4. 文章深度追问

针对每篇新闻，用户可以点击「深度追问」进入 RAG 对话模式：

- 系统自动抓取并解析原文内容
- 基于向量检索实现精准的上下文定位
- 支持多轮对话，深入探讨文章细节
- 流式输出，实时展示 AI 思考过程

### 5. 个性化推荐系统

通过多维度反馈机制构建用户画像：

- **显式反馈**：👍/👎 按钮直接表达偏好
- **偏好控制**：手动设置关注/屏蔽话题、优先/降权来源
- **语义画像**：基于反馈历史计算用户兴趣向量
- **智能重排**：结合多种信号动态调整内容排序

### 6. 历史归档与洞察

- **历史简报**：浏览过去 7 天的简报归档
- **周报生成**：Wired 风格的深度周刊，复盘一周技术版图
- **话题热力图**：可视化展示近 30 天的话题热度变化
- **实体时间线**：追踪特定公司/技术的历史动态

### 7. 多渠道通知

- **Web 界面**：现代化的深色主题仪表盘
- **邮件推送**：每日定时推送简报到邮箱
- **失败关闭**：未实现的通知渠道不会发送外部请求

---

## 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Frontend (Jinja2 + Vanilla JS)                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │  Dashboard  │  │  RAG Panel  │  │  History    │  │  Insights   │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           API Layer (FastAPI)                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │   Router    │  │  RAG Router │  │   Static    │  │   SSE       │    │
│  │  /api/v1/*  │  │  /api/v1/rag│  │   /static   │  │  Streaming  │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Service Layer                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ RSS Service │  │ LLM Service │  │ RAG Service │  │  Learning   │    │
│  │ (Feed Fetch)│  │ (DeepSeek)  │  │ (Embed+Retr)│  │  Service    │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ DB Service  │  │Email Service│  │Redis Service│  │Insights Svc │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Data Layer                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │   SQLite    │  │  ChromaDB   │  │    Redis    │  │  DeepSeek   │    │
│  │  (SQLModel) │  │  (Vectors)  │  │   (Cache)   │  │    API      │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       Infrastructure                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ APScheduler │  │  Structlog  │  │  Middleware │  │   Docker    │    │
│  │  (Cron)     │  │  (Logging)  │  │  (CORS/Trc) │  │  Compose    │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 数据流架构

```
                    ┌──────────────────┐
                    │   RSS Feeds      │
                    │  (10+ Sources)   │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  RSS Service     │
                    │  - 并发抓取       │
                    │  - Redis 缓存    │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  LLM Service     │
                    │  - 质量评分       │
                    │  - 摘要生成       │
                    │  - 文章去重       │
                    │  - 多样性控制     │
                    │  - Persona 注入  │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │   SQLite   │  │  ChromaDB  │  │  Frontend  │
     │  持久化    │  │  向量化    │  │   展示     │
     └────────────┘  └─────┬──────┘  └────────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │   RAG Pipeline   │
                    │  - Bi-Encoder    │
                    │  - BM25          │
                    │  - Cross-Encoder │
                    │  - HyDE          │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  DeepSeek API    │
                    │  流式问答生成     │
                    └──────────────────┘
```

---

## 技术栈详解

### 后端框架

| 技术 | 版本 | 用途 |
|------|------|------|
| **FastAPI** | 0.111.0+ | 高性能异步 Web 框架，自动生成 OpenAPI 文档 |
| **Uvicorn** | 0.30.1+ | ASGI 服务器，支持 HTTP/2 和 WebSocket |
| **Pydantic** | 2.7.4+ | 数据验证和序列化，Settings 管理配置 |
| **SQLModel** | 0.0.19+ | SQLAlchemy + Pydantic 融合，简化 ORM 操作 |

### 数据存储

| 技术 | 用途 | 特点 |
|------|------|------|
| **SQLite** | 主数据库 | 轻量级、零配置、适合单机部署 |
| **ChromaDB** | 向量数据库 | 本地持久化、支持 HNSW 索引 |
| **Redis** | 缓存层 | RSS 缓存、Token 统计、延迟监控 |

### AI/ML 组件

| 组件 | 模型 | 用途 |
|------|------|------|
| **LLM** | DeepSeek Chat | 摘要生成、问答、周报合成 |
| **Bi-Encoder** | BAAI/bge-m3 | 文本向量化（1024 维） |
| **Cross-Encoder** | ms-marco-MiniLM-L-6-v2 | 精排重排序 |
| **BM25** | rank-bm25 | 关键词检索 |

### 网页抓取

| 技术 | 用途 |
|------|------|
| **httpx** | 异步 HTTP 客户端 |
| **feedparser** | RSS/Atom 解析 |
| **trafilatura** | 高精度正文提取 |
| **BeautifulSoup4** | HTML 解析兜底 |

### 基础设施

| 技术 | 用途 |
|------|------|
| **APScheduler** | 定时任务（清理、邮件推送） |
| **structlog** | 结构化日志，支持 JSON 输出 |
| **Docker Compose** | 容器化部署 |

---

## 核心模块设计

### 1. RSS 聚合服务 (`rss_service.py`)

```python
# 核心流程
async def fetch_all_feeds(urls: list[str]) -> list[RSSResponse]:
    """
    1. 创建异步 HTTP 客户端
    2. 并发请求所有 RSS 源
    3. 解析 XML 为结构化数据
    4. 缓存到 Redis (15分钟)
    """
```

**设计亮点**：
- 自定义 User-Agent 绕过反爬检测
- Redis 缓存避免重复请求
- 优雅的错误处理，单个源失败不影响整体

### 2. LLM 服务 (`llm_service.py`)

```python
# 两阶段生成流程
async def generate_daily_summary(...):
    # Phase 1: 质量评分
    high_quality, report = await self._score_articles(articles)
    
    # Phase 2: 摘要生成
    response = await self.client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": EDITOR_PROMPT + persona_context},
            {"role": "user", "content": input_json}
        ],
        response_format={"type": "json_object"}
    )
```

**Persona 注入机制**：
```
USER PERSONALITY & PREFERENCE GUIDELINES:
- [Instruction] 多关注 AI 大模型进展
- [MUST COVER topic] GPT, Claude, LLaMA
- [NEVER include topic] 股市行情
- [Preferred source] Ars Technica
- [De-prioritize source] 某某营销号
```

### 3. RAG 服务 (`rag_service.py`)

这是系统最复杂的模块，实现了完整的检索增强生成管道：

#### 3.1 文章摄入流程

```
URL → 安全检查 → 网页抓取 → 正文提取 → 质量评估 → 分块 → 向量化 → 存储到 ChromaDB
```

**内容质量评估**：
- 段落密度分析
- 噪声词比例检测
- 文本长度评估
- 输出质量评分 (0.0-1.0) 和诊断信息

#### 3.2 混合检索策略

```
┌─────────────────────────────────────────────────────────────┐
│                      Query Processing                        │
│  ┌─────────────┐                                            │
│  │ User Query  │                                            │
│  └──────┬──────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐     ┌─────────────┐                        │
│  │ HyDE Rewrite│────▶│ Bi-Encoder  │                        │
│  │ (Optional)  │     │ Embedding   │                        │
│  └─────────────┘     └──────┬──────┘                        │
│                             │                                │
└─────────────────────────────┼────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
     ┌────────────┐   ┌────────────┐   ┌────────────┐
     │  Vector    │   │   BM25     │   │  Personal  │
     │  Recall    │   │  Keyword   │   │  Centroid  │
     │  (Top-20)  │   │  (Top-20)  │   │   Bonus    │
     └─────┬──────┘   └─────┬──────┘   └─────┬──────┘
           │                │                │
           └────────────────┼────────────────┘
                            │
                            ▼
                   ┌────────────────┐
                   │  RRF Fusion    │
                   │  (k=60)        │
                   └───────┬────────┘
                           │
                           ▼
                   ┌────────────────┐
                   │ Cross-Encoder  │
                   │   Rerank       │
                   └───────┬────────┘
                           │
                           ▼
                   ┌────────────────┐
                   │  Top-3 Chunks  │
                   │  for LLM       │
                   └────────────────┘
```

**RRF (Reciprocal Rank Fusion) 公式**：
```
RRF_score(d) = Σ (1 / (k + rank(d)))
```

#### 3.3 HyDE 查询改写

```python
async def _hyde_rewrite(question: str) -> str:
    """
    让 LLM 生成一个假设性回答，
    将问题和假设回答的向量取平均，
    增强对模糊/短查询的召回效果。
    """
```

#### 3.4 个性化加权

```python
# 正反馈质心相似度 → 加分
bonus = max(0, similarity_pos) * 3.0

# 负反馈质心相似度 → 减分
penalty = max(0, similarity_neg) * 2.0

total_score = cross_score + bonus - penalty
```

### 4. 学习服务 (`learning_service.py`)

```python
async def get_user_feedback_profiles() -> tuple[np.ndarray, np.ndarray]:
    """
    从用户反馈历史计算正/负质心向量：
    1. 获取所有 👍 文章的 URL
    2. 从 NewsItem 提取 headline + key_points
    3. 用 Bi-Encoder 编码
    4. 计算平均向量并归一化
    """
```

**重排序策略**：
- 屏蔽话题：直接从列表移除
- 关注话题：+0.3 分
- 优先来源：+0.15 分
- 降权来源：-0.2 分
- 正反馈相似度：+0.7 × cosine_sim
- 负反馈相似度：-0.3 × cosine_sim

### 5. 数据库服务 (`db_service.py`)

**级联删除设计**：
```python
class DailySummary(SQLModel, table=True):
    top_news: List[NewsItem] = Relationship(
        back_populates="summary",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
```

**自动清理机制**：
```python
async def cleanup_old_data(session, days_to_keep=7):
    """
    1. 查找过期摘要
    2. 提取关联的文章 URL
    3. 删除 ChromaDB 向量集合
    4. 删除反馈和聊天记录
    5. 级联删除摘要和新闻项
    """
```

### 6. 调度服务 (`scheduler.py`)

```python
# 定时任务配置
_scheduler.add_job(
    _run_cleanup,
    trigger=IntervalTrigger(hours=6),
    id="cleanup_old_data"
)

_scheduler.add_job(
    _run_daily_push,
    trigger=CronTrigger(hour=8, minute=0),
    id="daily_push"
)
```

---

## Board 源类型

每个 Board 可以配置不同的源类型：

| 源类型 | 描述 | 配置示例 |
|--------|------|----------|
| `rss` | 从 RSS feeds 抓取 | `{"feeds": ["https://hnrss.org/frontpage"]}` |
| `hackernews` | HN 热门故事 + 评论 | `{"fetch_top_stories": 30, "min_score": 100}` |
| `reddit` | Reddit 帖子 | `{"subreddits": [{"subreddit": "LocalLLaMA"}]}` |
| `github` | GitHub 用户动态和仓库发布 | `{"users": ["openai"], "repos": [{"owner": "openai", "repo": "whisper"}]}` |
| `multi` | 并行组合多种源 | `{"sources": {"rss": {...}, "hackernews": {...}}}` |
| `pure_llm` | LLM 生成原创内容 | `{"items_per_day": 5, "style": "fun facts"}` |

**源适配器架构**：

```
app/services/source_adapters/
├── base.py           # BaseAdapter 抽象基类
├── rss_adapter.py    # RSS 源适配器
├── hn_adapter.py     # Hacker News 适配器
├── reddit_adapter.py # Reddit 适配器
├── github_adapter.py # GitHub 适配器
└── pure_llm_adapter.py # 纯 LLM 适配器
```

---

## 数据模型

### ER 图

```
┌─────────────────┐       ┌─────────────────┐
│  DailySummary   │       │    NewsItem     │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │───┐   │ id (PK)         │
│ date (Unique)   │   │   │ headline        │
│ overview        │   │   │ category        │
│ stats_json      │   └──▶│ key_points      │
│ created_at      │       │ tags            │
└─────────────────┘       │ original_link   │
                          │ source          │
                          │ summary_id (FK) │
                          └─────────────────┘

┌─────────────────┐       ┌─────────────────┐
│  UserFeedback   │       │   UserPersona   │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │
│ article_url (UQ)│       │ content         │
│ sentiment       │       │ category        │
│ created_at      │       │ is_active       │
└─────────────────┘       │ created_at      │
                          └─────────────────┘

┌─────────────────┐
│   ChatMessage   │
├─────────────────┤
│ id (PK)         │
│ article_url     │
│ role            │
│ content         │
│ timestamp       │
└─────────────────┘
```

### 字段说明

#### DailySummary
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| date | str | 日期 (YYYY-MM-DD)，唯一索引 |
| overview | str | 当日概览文本 |
| stats_json | str | 推荐报告 JSON |
| created_at | datetime | 创建时间 |

#### NewsItem
| 字段 | 类型 | 说明 |
|------|------|------|
| headline | str | 标题 |
| category | str | 分类（AI、硬件、软件等） |
| key_points | str | 要点列表 JSON |
| tags | str | 标签列表 JSON |
| original_link | str | 原文链接 |
| source | str | 来源名称 |
| summary_id | int | 关联摘要 ID |

#### UserFeedback
| 字段 | 类型 | 说明 |
|------|------|------|
| article_url | str | 文章 URL（唯一） |
| sentiment | int | 1=喜欢, -1=不喜欢 |

#### UserPersona
| 字段 | 类型 | 说明 |
|------|------|------|
| content | str | 偏好内容 |
| category | str | 分类：instruction/extracted/focus_topic/block_topic/prefer_source/avoid_source |
| is_active | bool | 是否生效 |

---

## API 接口设计

### 概览

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/ping` | 健康检查 |
| GET | `/api/v1/status` | 私有运行诊断（数据库/功能/认证状态，不返回密钥） |
| GET | `/api/v1/summary` | 获取/生成每日简报 |
| GET | `/api/v1/history` | 历史简报归档 |
| GET | `/api/v1/feed` | RSS 2.0 订阅源 |
| GET | `/api/v1/metrics` | 系统指标统计 |
| GET | `/api/v1/persona` | 获取用户偏好 |
| POST | `/api/v1/persona` | 添加偏好 |
| DELETE | `/api/v1/persona/{id}` | 删除偏好 |
| POST | `/api/v1/rag/ingest` | 文章向量化 |
| POST | `/api/v1/rag/query` | RAG 问答（SSE） |
| POST | `/api/v1/rag/feedback` | 提交反馈 |
| GET | `/api/v1/insights/heatmap` | 话题热力图 |
| GET | `/api/v1/insights/timeline` | 实体时间线 |
| GET | `/api/v1/boards` | 列出所有 Board |
| POST | `/api/v1/boards` | 创建新 Board |
| POST | `/api/v1/boards/wizard` | Board 创建向导 |

### 详细接口说明

#### GET /api/v1/summary

获取或生成每日简报。

**参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| force | bool | 否 | 强制重新生成 |
| date | str | 否 | 指定日期 (YYYY-MM-DD) |
| preference | str | 否 | 一次性偏好指令 |
| save_preference | bool | 否 | 是否保存为长期偏好 |

**响应**：
```json
{
  "date": "2026-04-22",
  "overview": "今日 AI 领域迎来多项突破...",
  "top_news": [
    {
      "headline": "GPT-5 发布在即",
      "category": "AI",
      "key_points": ["性能提升 3 倍", "支持 100 万 token 上下文"],
      "tags": ["#GPT", "#OpenAI", "#LLM"],
      "original_link": "https://...",
      "source": "TechCrunch",
      "feedback_sentiment": null,
      "persona_score": 0.85
    }
  ],
  "source_stats": {"TechCrunch": 3, "Ars Technica": 2},
  "recommendation_report": {
    "total_fetched": 50,
    "passed_count": 12,
    "excluded_samples": ["某低质量文章标题"]
  }
}
```

#### POST /api/v1/rag/query

RAG 问答接口，返回 SSE 流。

**请求体**：
```json
{
  "url": "https://example.com/article",
  "question": "这篇文章提到的核心技术是什么？"
}
```

**响应流**：
```
data: [METADATA]{"type":"scoring_explain","scores":[...]}[/METADATA]
data: 这篇文章主要讨论了...
data: 核心技术包括以下几点：
data: 1. **Transformer 架构** [1]
data: 2. **注意力机制** [2]
data: [DONE]
```

---

## MCP Server 集成

Argos 支持 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/)，可以将系统能力暴露给 AI 助手（如 Claude、Cursor、Windsurf）。

### 可用工具

| 工具 | 描述 |
|------|------|
| `get_daily_summary` | 获取指定 Board 的今日简报 |
| `generate_summary` | 触发简报生成 |
| `ask_article` | 对已摄入文章进行 RAG 问答 |
| `search_news` | 跨新闻历史的关键词搜索 |
| `list_boards` | 列出所有内容 Board |
| `add_feedback` | 点赞/点踩文章以个性化 |
| `get_user_interests` | 查看当前用户偏好 |
| `get_system_status` | 系统健康和配置信息 |

### 使用方式

```bash
# stdio 传输（用于 IDE 集成）
python mcp_server.py

# 或添加到 MCP 客户端配置
{
  "mcpServers": {
    "argos": {
      "command": "python",
      "args": ["path/to/Argos/mcp_server.py"]
    }
  }
}
```

---

## 前端界面

### 设计理念

- **深色主题**：减少视觉疲劳，适合长时间阅读
- **玻璃态设计**：半透明卡片 + 模糊背景，现代感十足
- **响应式布局**：适配桌面和移动设备

### 主要组件

#### 1. 仪表盘 (Dashboard)

```
┌─────────────────────────────────────────────────────────────┐
│  Argos                                    [偏好][周刊][往日][洞察]  │
│  2026年4月22日 星期三                                        │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 今日概览：AI 领域迎来多项突破，OpenAI 发布 GPT-5...   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  [AI × 5] [硬件 × 3] [软件 × 4] [安全 × 2]                  │
│                                                             │
│  来源分布: [TechCrunch × 3] [Ars Technica × 2] ...          │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │ [TechCrunch] [AI]                                    │   │
│  │ GPT-5 发布在即：性能提升 3 倍                        │   │
│  │ • 支持 100 万 token 上下文                           │   │
│  │ • 多模态能力大幅增强                                 │   │
│  │ • 推理速度提升 200%                                  │   │
│  │ #GPT #OpenAI #LLM                                   │   │
│  │                                          [👍][👎] [深度追问] │
│  └─────────────────────────────────────────────────────┘   │
│  ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

#### 2. RAG 对话面板

```
┌─────────────────────────────────────┐
│ 💬 深度追问                    [×]  │
│ GPT-5 发布在即：性能提升 3 倍        │
├─────────────────────────────────────┤
│                                     │
│ [User] 这篇文章提到的核心技术是什么？│
│                                     │
│ [AI] 这篇文章主要讨论了...          │
│ 核心技术包括：                      │
│ 1. **Transformer 架构** [1]        │
│ 2. **注意力机制** [2]              │
│                                     │
├─────────────────────────────────────┤
│ [输入问题...]                  [发送]│
└─────────────────────────────────────┘
```

#### 3. 偏好设置面板

```
┌─────────────────────────────────────┐
│ 偏好设置                       [×]  │
├─────────────────────────────────────┤
│ 长期偏好                            │
│ ┌─────────────────────────────────┐ │
│ │ 多关注 AI 大模型进展        [×] │ │
│ │ 少看硬件评测                [×] │ │
│ └─────────────────────────────────┘ │
│                                     │
│ ─────────────────────────────────── │
│ 显式偏好控制                        │
│                                     │
│ 关注话题                            │
│ [GPT ×] [LLaMA ×] [添加...]        │
│                                     │
│ 屏蔽话题                            │
│ [股市 ×] [添加...]                 │
│                                     │
│ 优先来源                            │
│ [Ars Technica ×] [添加...]         │
│                                     │
│ 降权来源                            │
│ [添加...]                          │
│                                     │
│ ─────────────────────────────────── │
│ 今日系统消耗                        │
│ 消耗 Tokens: 12,345                 │
│ 简报耗时 (P50): 8.5 s               │
│ 简报耗时 (P99): 15.2 s              │
└─────────────────────────────────────┘
```

---

## 项目亮点

### 1. 多源聚合与 Board 系统

支持 RSS、Hacker News、Reddit、GitHub 等多种源类型，每个 Board 独立配置：

- **灵活的源适配器架构**：易于扩展新的源类型
- **Board 创建向导**：AI 引导式配置
- **多源并行组合**：一个 Board 可聚合多种源

### 2. 完整的 RAG 管道

从网页抓取到流式问答，实现了完整的检索增强生成流程：

- **智能摄入**：自动抓取、解析、分块、向量化
- **混合检索**：向量召回 + BM25 关键词召回 + RRF 融合
- **精排优化**：Cross-Encoder 重排序 + 个性化加权
- **查询增强**：HyDE 假设性回答改写
- **流式输出**：SSE 实时展示 AI 思考过程

### 3. 多维度个性化推荐

```
┌─────────────────────────────────────────────────────────────┐
│                    个性化推荐系统                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  显式偏好                    隐式反馈                        │
│  ┌─────────────┐            ┌─────────────┐                │
│  │ 关注话题    │            │   👍 反馈   │                │
│  │ 屏蔽话题    │            │   👎 反馈   │                │
│  │ 优先来源    │            │             │                │
│  │ 降权来源    │            │             │                │
│  └──────┬──────┘            └──────┬──────┘                │
│         │                          │                        │
│         │    ┌────────────────┐    │                        │
│         └───▶│  语义画像计算   │◀───┘                        │
│              │  (正/负质心)    │                            │
│              └───────┬────────┘                             │
│                      │                                      │
│                      ▼                                      │
│              ┌────────────────┐                             │
│              │   智能重排序   │                             │
│              │  (加权融合)    │                             │
│              └────────────────┘                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3. LLM 驱动的质量过滤与去重

不是简单聚合，而是通过 LLM 对每篇文章进行质量评分：

- **相关性评估**：是否与科技/AI/编程相关
- **新闻价值**：是否为有价值的新闻，而非广告或公关稿
- **教育意义**：是否具有讨论或学习价值

**文章去重机制**：

生成简报时自动排除过去 3 天已展示的文章，避免用户重复看到相同内容：

```python
recent_urls = await db_service.get_recent_article_urls(session, days=3)
raw_articles = [a for a in raw_articles if a["link"] not in recent_urls]
```

**多样性控制**：

用户偏好最多只影响 30-40% 的文章，防止信息茧房：

```
IMPORTANT: These preferences should influence article PRIORITY,
but do NOT let them dominate the entire briefing. At most 30-40%
of articles should match user interests — the rest should cover
other important news of the day for breadth.
```

### 4. 可观测性设计

- **结构化日志**：基于 structlog，支持 JSON 格式输出
- **TraceID 追踪**：每个请求分配唯一 ID，便于问题定位
- **Token 统计**：实时记录 LLM 消耗
- **延迟监控**：P50/P99 延迟统计

### 5. 安全防护

```python
# URL 安全检查
async def ensure_public_url_target(url: str) -> str:
    """
    1. 检查协议（仅允许 http/https）
    2. 检查主机名（阻止 localhost、.local）
    3. DNS 解析后检查 IP（阻止私有地址）
    4. 解析 DNS 后再次检查目标 IP；为兼容部分透明代理，保留对 198.18.0.0/15 Fake IP 的放行
    """
```

### 6. 优雅的异步设计

- 全异步 I/O（httpx、aiosqlite、AsyncOpenAI）
- 后台 Worker 处理文章向量化
- SSE 流式响应，避免长时间阻塞

### 7. MCP Server 集成

通过 Model Context Protocol 暴露系统能力给 AI 助手：

- 支持 Claude、Cursor、Windsurf 等 MCP 客户端
- 提供简报查询、RAG 问答、偏好管理等工具
- 便于构建 AI Agent 工作流

### 8. 多渠道通知推送

支持多种推送方式：

- **邮件**：SMTP 发送 HTML 简报
- **失败关闭**：未实现的通知渠道会记录为失败，不会发送外部请求

---

## 部署指南

### Docker 部署（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. 配置环境
cp .env.template .env
# 编辑 .env 设置 LLM_API_KEY

# 3. 启动服务
docker compose up -d

# 4. 访问
open http://127.0.0.1:8000
```

### 一键启动（本地开发推荐）

项目提供启动脚本，自动处理虚拟环境、依赖安装、Redis 启动、模型下载：

```bash
# macOS / Linux
chmod +x scripts/start.sh
./scripts/start.sh

# Windows — 双击或运行：
scripts\Open_Web_Dashboard.bat
```

首次运行时会：
1. 创建虚拟环境并安装依赖
2. 提示输入 LLM API Key（自动创建 `.env`）
3. 检查/启动 Redis
4. 预下载 RAG 嵌入模型（约 650 MB，一次性）
5. 启动后端并打开浏览器

### 手动安装

<details>
<summary>点击展开详细步骤</summary>

```bash
# 1. 克隆仓库
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. 创建虚拟环境
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境
cp .env.template .env
# 编辑 .env 设置 LLM_API_KEY

# 5. （可选）预下载 RAG 模型
python scripts/download_models.py

# 6. 启动 Redis
# Windows: 启动脚本已处理
# Linux/macOS: redis-server --daemonize yes

# 7. 启动应用
uvicorn main:app --reload

# 8. 打开 http://127.0.0.1:8000
```

</details>

---

## 配置说明

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|------|------|
| `LLM_API_KEY` | ✅ | - | 任意 OpenAI 兼容 LLM 的 API Key |
| `LLM_MODEL` | | `deepseek-chat` | 模型名称 |
| `LLM_BASE_URL` | | - | API 端点；使用通用 `LLM_API_KEY` 时需显式设置，旧版 DeepSeek 回退只在未设置 `LLM_API_KEY` 时生效 |
| `LLM_TIMEOUT` | | `180` | 请求超时（秒） |
| `DEEPSEEK_API_KEY` | | - | 旧版兼容，作为 LLM_API_KEY 的备选 |
| `SQLALCHEMY_DATABASE_URI` | | `sqlite+aiosqlite:///./data/sqlite/argos.db` | 数据库连接 |
| `REDIS_URL` | | `redis://localhost:6379` | Redis 连接 |
| `CHROMA_DB_DIR` | | `./data/chroma` | 向量数据库目录 |
| `CORS_ORIGINS` | | `http://localhost:5173,...` | 允许的前端源；设置为 `*` 时会关闭 credentialed CORS |
| `CORS_ALLOW_CREDENTIALS` | | `True` | 对明确列出的来源允许 credentialed CORS |
| `GITHUB_TOKEN` | | - | GitHub Token（提高速率限制） |
| `HN_FETCH_TOP_STORIES` | | `30` | HN 热门故事数量 |
| `HN_MIN_SCORE` | | `100` | HN 最低分数阈值 |
| `REDDIT_FETCH_COMMENTS` | | `5` | Reddit 每帖评论数 |
| `SMTP_HOST` | | - | SMTP 服务器 |
| `SMTP_USER` | | - | SMTP 用户名 |
| `SMTP_PASSWORD` | | - | SMTP 密码 |
| `EMAIL_SUBSCRIBERS` | | `[]` | 订阅者邮箱列表 |
| `DAILY_PUSH_TIME` | | `08:00` | 每日推送时间 |
| `NOTIFY_CHANNELS` | | `email` | 通知渠道；当前仅实现 `email`，留空则禁用定时外部通知 |

---

## 未来展望

### 短期优化

- [ ] 持续扩展单元测试、集成测试和 smoke 验收覆盖率
- [ ] 优化前端性能（虚拟滚动、懒加载）
- [ ] 更多源适配器（YouTube、更多 RSSHub 场景等）

### 中期规划

- [ ] 保持私有单用户/小型自托管定位，继续加固 API Key、备份恢复、URL 安全和运行诊断
- [ ] 向量数据库保持可插拔，默认继续使用本地 ChromaDB
- [ ] 移动端适配或轻量 PWA
- [ ] AI Agent 工作流深度集成

### 长期愿景

- [ ] 构建本地优先的插件生态
- [ ] 改进个人知识库与简报协同
- [ ] 多语言内容处理
- [ ] 更完善的小型自托管部署方案

---

## 许可证

MIT License

---

## 致谢

本项目使用了以下开源项目：

- [FastAPI](https://fastapi.tiangolo.com/)
- [SQLModel](https://sqlmodel.tiangolo.com/)
- [ChromaDB](https://www.trychroma.com/)
- [Sentence Transformers](https://www.sbert.net/)
- [DeepSeek](https://www.deepseek.com/)
- [trafilatura](https://trafilatura.readthedocs.io/)

---

*最后更新：2026年4月28日*
