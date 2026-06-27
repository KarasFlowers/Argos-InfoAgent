# 项目优化方案

## 一、代码质量优化

### 1.1 拆分 `/summary` 端点

**现状**：`router.py` 中 `/summary` 端点约 200 行，混合了缓存查询、分布式锁、摘要生成、多视角处理、RAG 入队、rerank、catchup、events、source_analysis 等职责。

**方案**：提取为 `SummaryService` 类

```python
# app/services/summary_service.py
class SummaryService:
    async def get_or_generate(self, ...) -> DailySummaryResponse:
        cached = await self._try_cache(...)
        if cached: return cached
        async with self._lock:
            cached = await self._try_cache(...)
            if cached: return cached
            return await self._generate(...)

    async def _try_cache(self, ...) -> DailySummaryResponse | None: ...
    async def _generate(self, ...) -> DailySummaryResponse: ...
    async def _attach_enrichments(self, ...): ...
```

**收益**：路由文件减少 150+ 行，业务逻辑可单元测试。

### 1.2 统一错误处理

**现状**：约 20+ 处使用 `try/except Exception: logger.debug(...)` 静默吞掉异常，真正的 bug 永远不会暴露。

**方案**：
- 基础设施错误（网络超时、DB 连接失败）→ `logger.exception()` 并向上传播
- 业务可降级逻辑（catchup、events、source_analysis 失败）→ 明确标注 "optional"，只 catch 预期的异常类型

```python
# 推荐
try:
    await self._attach_events(summary)
except (NetworkError, DataError) as e:
    logger.warning("Event enrichment skipped", exc_info=e)
    summary.events = []

# 不推荐
try:
    await self._attach_events(summary)
except Exception:
    logger.debug("Events skipped")
```

**收益**：避免 bug 被静默吞掉。

### 1.3 重构 `app.js`

**现状**：2000 行单体文件，21 个全局 `let` 变量，所有功能通过全局函数 + DOM id 耦合。

**方案**（分三步）：
1. **第一步**（低风险）：按功能拆成多个文件 —— `board.js`、`summary.js`、`rag.js`、`settings.js`，用 `<script>` 按序加载
2. **第二步**（中风险）：用简单的 Module 模式替代全局变量 —— 每个功能模块返回一个对象，不污染全局命名空间
3. **第三步**（可选）：引入 Svelte 或 Preact 做组件化

**收益**：前端代码可维护，多人协作不冲突。

### 1.4 清理 `router.py` 中的内联逻辑

**现状**：`_test_single_feed`(50行)、`_discover_feeds`(40行)、`_parse_feed_links`(20行) 定义在路由文件里。

**方案**：移到 `app/services/rss_service.py`

```python
# app/services/rss_service.py
async def test_single_feed(url: str, timeout: float = 15.0) -> dict: ...
async def discover_feeds(homepage: str, timeout: float = 8.0, limit: int = 4) -> list[str]: ...
def parse_feed_links(html_text: str, base_url: str, limit: int = 4) -> list[str]: ...
```

**收益**：`router.py` 减少 110 行，职责清晰。

### 1.5 删除纯 Facade 文件

**现状**：
- `app/services/rag_service.py`（36 行，只做 `from app.services.rag import *`）
- `app/services/llm_service.py`（类似）
- `app/services/db_service.py`（类似）

**方案**：直接删除这三个文件，更新 import 路径。可以用 IDE 的全局搜索替换。

```diff
- from app.services.rag_service import ingest
+ from app.services.rag import ingest
```

**收益**：减少三层间接调用，提升可读性。

### 1.6 `requirements.txt` 加版本锁定

**现状**：所有依赖没有版本号（或只有最低版本），不同时间安装得到不同版本。

**方案**：运行 `pip freeze` 生成锁文件，或使用 `pip-compile` 管理

```
# requirements.in（手动维护）
fastapi>=0.111.0
uvicorn[standard]
...

# requirements.txt（自动生成）
fastapi==0.115.0
uvicorn==0.30.0
...
```

**收益**：构建可复现。

### 1.7 `pyproject.toml` 补全项目元数据

**现状**：缺少 `[project]` 段，无法 `pip install -e .`。

**方案**：

```toml
[project]
name = "argos"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]",
    # ...
]
```

---

## 二、用户体验优化

### 2.1 摘要生成加进度反馈

**现状**：生成摘要需 30-60 秒，用户只看到 spinner。

**方案**：后端用 SSE 推送进度，前端显示逐步状态

```
[SSE] → event: progress, data: {"stage": "fetching", "label": "正在抓取 RSS 源..."}
[SSE] → event: progress, data: {"stage": "dedup", "label": "正在去重..."}
[SSE] → event: progress, data: {"stage": "scoring", "label": "AI 正在评分..."}
[SSE] → event: progress, data: {"stage": "summary", "label": "AI 编辑正在撰写..."}
[SSE] → event: result, data: {summary object}
```

**前端改动**：

```javascript
// 用 EventSource 替代 fetch
const es = new EventSource(`/api/v1/summary/stream?board=${slug}`);
es.addEventListener('progress', (e) => {
    updateProgressBar(JSON.parse(e.data));
});
es.addEventListener('result', (e) => {
    renderSummary(JSON.parse(e.data));
    es.close();
});
```

**后端改动**：新增 `/summary/stream` 端点，生成过程中发送 SSE 事件，最终发送完整结果。

**收益**：用户知道进度，减少焦虑感。

### 2.2 Board Wizard 简化流程

**现状**：Wizard + Manual 双入口，用户先对话然后跳到表单，流程割裂。

**方案**：合并为一个流程

1. 用户点击"新建板块"
2. 弹窗显示输入框和快捷模板
3. 用户描述需求（或用模板）
4. 后端直接返回填充好表单的配置
5. 用户在表单中微调 → 保存

**关键改动**：去掉"预览"步骤（大多数用户不需要），把 wizard 结果直接填入表单，而不是先生成再应用。

**收益**：从 5 步减少到 3 步。

### 2.3 前端 CDN 依赖加 fallback

**现状**：`marked.js` 从 `cdn.jsdelivr.net` 加载，无 fallback。

**方案**：

```html
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
    if (typeof marked === 'undefined') {
        document.write('<script src="/static/marked.min.js"><\/script>');
    }
</script>
```

**收益**：CDN 挂了不影响核心功能。

### 2.4 合并 /summary 和 /briefing

**现状**：两个端点返回类似但不同的数据结构，前端和 API 使用者容易混淆。

**方案**：
- 保留 `/summary` 作为标准 API 返回（`DailySummaryResponse`）
- 删除 `/briefing`，或将 `/briefing` 改为 `/summary?format=briefing` 的别名

**收益**：减少 API 表面，降低认知负担。

### 2.5 改进首次启动体验

**现状**：
- 首次启动要先下载 RAG 模型（~650MB），用户不知道发生了什么
- `.env` 需要手动编辑 API key

**方案**：
- 启动时打印清晰的进度日志
- 首次启动检测到没有 API key 时，在终端交互式提示输入
- RAG 模型改为懒加载（首次使用时才下载），而不是启动时阻塞

---

## 三、优先级

| 优先级 | 项目 | 类型 | 工作量 |
|--------|------|------|--------|
| P0 | 1.1 拆分 /summary 端点 | 代码 | 中 |
| P0 | 1.2 统一错误处理 | 代码 | 小 |
| P0 | 1.5 删除 Facade 文件 | 代码 | 极小 |
| P1 | 2.1 摘要生成进度反馈 | UX | 中 |
| P1 | 1.4 清理 router 内联逻辑 | 代码 | 小 |
| P1 | 1.6 依赖版本锁定 | 代码 | 小 |
| P2 | 1.3 重构 app.js | 代码 | 大 |
| P2 | 2.2 Board Wizard 简化 | UX | 小 |
| P2 | 2.4 合并 /summary 和 /briefing | UX | 小 |
| P3 | 1.7 pyproject.toml 补全 | 代码 | 极小 |
| P3 | 2.3 CDN fallback | UX | 极小 |
| P3 | 2.5 首次启动体验 | UX | 中 |
