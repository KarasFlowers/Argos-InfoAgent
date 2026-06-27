# 重构精简计划

## 1. 移除 Repository 层

- 删除 `app/services/repositories/` 目录（5 个文件）
- 合并 `db_service.py`，直接暴露 `AsyncSession` 和查询方法
- 业务代码直接使用 SQLModel query，不再经过 repo 封装

**理由**：单用户 SQLite 不需要 Repository 模式

## 2. 合并 Service Facade

- `llm_service.py` → 直接导入 `app/services/llm/` 中的模块
- `db_service.py` → 直接导入 SQLModel 操作
- `rag_service.py` → 直接导入 `app/services/rag/` 中的模块

三个 facade 文件只是把 import 包了一层，删除后不影响功能

## 3. 简化通知系统

- 删除 `app/services/notification/` 目录
- 仅保留一个 `email_service.py`（SMTP 发信）
- 移除 Webhook、Bark、Telegram 渠道

**理由**：单用户最多用 Email，其他渠道从未被使用

## 4. 替换 APScheduler

- 删除 `app/core/scheduler.py`
- 改为简单的 `asyncio.create_task` + `while` 循环
- 启动时在 `lifespan` 中 spawn 后台协程

**理由**：APScheduler（447 行）太重量级，简单的定时循环就够

## 5. 精简 Board Wizard

- 移除 wizard 管线中的 feed 发现、验证、RSSHub 集成、Tavily 搜索
- 简化为用户手动输入 RSS URL 即可完成 board 创建
- 删除 `app/services/llm/wizard.py`
- 删除相关的 wizard prompt 模板（3 个文件）
- 清理 router 中对应的端点

**理由**：这个功能等价于一个"AI RSS 助手"，对核心产品不必要

## 6. 删除 RAG 模块（或独立）

- 删除 `app/services/rag/` 目录
- 删除 `rag_router.py`
- 可考虑拆成单独的独立项目

**理由**：RAG 功能的复杂度（ChromaDB、bi-encoder、cross-encoder、BM25、HyDE、ingest workers）和新闻聚合无关，适合独立项目

## 7. 删除 MCP Server

- 删除 `mcp_server.py`

**理由**：这是另一个项目的入口点，和主应用功能无关

## 8. 删除 TaskRun 可观测性

- 删除 `domain.py` 中的 `TaskRun` 模型
- 删除对应数据库表
- 删除所有记录 `TaskRun` 的代码

**理由**：单用户本地应用不需要后台任务追踪

## 9. 清理 Prompt 存储

- 删除 `domain.py` 中的 `PromptConfig` 和 `ModelApiConfig` 模型
- 删除对应数据库表
- 只保留 `app/prompts/` 目录下的 markdown 文件

**理由**：hot-reload 的 prompt 管理对个人工具是过度设计

## 10. 简化 Source Adapters

- 删除 `app/services/source_adapters/` 目录
- 每个源类型简化为独立函数（`fetch_rss()`、`fetch_hn()`、`fetch_reddit()` 等）
- 在 `rss_service.py` 中直接调用

**理由**：7 个文件的 adapter 模式对于 5 种数据源过于形式化

## 11. 缩小 API 表面

删除以下几乎不会被调用的端点：

| 路径 | 理由 |
|------|------|
| `/briefing/refine` + `/{session_id}` | 简报精修功能过于精细 |
| `/boards/wizard/preview` | wizard 的一部分 |
| `/boards/wizard/fix-feeds` | wizard 的一部分 |
| `/boards/{slug}/sources/discover` | 自动发现功能 |
| `/boards/{slug}/sources/{id}/alternatives` | 建议替代源 |
| `/boards/prompts/templates` | PromptConfig 的产物 |
| `/boards/{slug}/perspectives` | 多视角功能，无人使用 |
| `/cache` | 调试用端点 |
| `/sources/coverage` | 跨源覆盖分析 |
| `/sources/dashboard` | 源健康仪表盘 |
| `/admin/sources/{id}/health_log` | 过于详细的健康记录 |
| `/insights/heatmap` / `timeline` / `topic_tree` / `trending` | 四个洞察端点，可合并为一个 |

## 12. 数据模型清理

删除以下表对应的模型：

| 表 | 理由 |
|----|------|
| `TaskRun` | 见第 8 项 |
| `PromptConfig` | 见第 9 项 |
| `ModelApiConfig` | 见第 9 项 |
| `SourceHealthLog` | 不需要粒度的健康记录 |
| `UserMemory` | 记忆提取功能过于复杂 |
| `DailyReportRefinementSession` | 精修 session 过于精细 |
| `SummaryViewLog` | 已由 ArticleReadState 替代 |

## 优先级建议

| 优先级 | 项目 | 预估工作量 |
|--------|------|-----------|
| P0 | 6. 删除 RAG 模块 | 小 |
| P0 | 7. 删除 MCP Server | 极小 |
| P0 | 11. 缩小 API 表面 | 中 |
| P1 | 1. 移除 Repository 层 | 中 |
| P1 | 2. 合并 Service Facade | 小 |
| P1 | 10. 简化 Source Adapters | 小 |
| P2 | 4. 替换 APScheduler | 中 |
| P2 | 9. 清理 Prompt 存储 | 小 |
| P2 | 12. 数据模型清理 | 中 |
| P3 | 3. 简化通知系统 | 小 |
| P3 | 5. 精简 Board Wizard | 大 |
| P3 | 8. 删除 TaskRun | 小 |
