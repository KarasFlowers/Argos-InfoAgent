# Argos 项目面试问答

> 模拟技术面试场景，深入探讨项目设计决策与技术细节

---

## 目录

- [项目概述类问题](#项目概述类问题)
- [架构设计类问题](#架构设计类问题)
- [RAG 技术类问题](#rag-技术类问题)
- [LLM 应用类问题](#llm-应用类问题)
- [数据库与存储类问题](#数据库与存储类问题)
- [性能优化类问题](#性能优化类问题)
- [系统设计类问题](#系统设计类问题)
- [工程实践类问题](#工程实践类问题)

---

## 项目概述类问题

### Q1: 请简单介绍一下这个项目

**回答**：

Argos 是一个基于 LLM 的智能科技资讯聚合系统。它的核心价值在于解决技术人员信息过载的问题——不是简单地聚合 RSS，而是通过 AI 技术实现智能筛选、结构化摘要和个性化推荐。

具体来说，系统支持多种内容源（RSS、Hacker News、Reddit、GitHub、纯 LLM 生成），通过任意 OpenAI 兼容的 LLM 进行质量评分和摘要生成，产出一份结构化的每日简报。用户可以对每篇文章进行深度追问（基于 RAG 技术），系统还会根据用户的反馈持续优化推荐结果。

从技术栈来看，后端使用 FastAPI + SQLModel + ChromaDB + Redis，前端是 Jinja2 模板 + 原生 JS，部署支持 Docker Compose。系统还提供 MCP Server，可与 Claude、Cursor 等 AI 助手集成。

---

### Q2: 为什么选择做这个项目？解决了什么痛点？

**回答**：

做这个项目的初衷是解决我自己的痛点。作为技术人员，我每天需要追踪大量科技资讯，但传统的 RSS 阅读器只是简单聚合，我仍然需要花大量时间筛选和阅读。

具体痛点有三个：

1. **信息噪音大**：每个 RSS 源每天可能有几十篇文章，但真正有价值的可能只有几篇。我需要 LLM 帮我做质量筛选。

2. **阅读效率低**：即使筛选后，逐篇阅读仍然耗时。我需要结构化的摘要，快速了解要点。

3. **缺乏个性化**：不同人关注的方向不同，通用的推荐不够精准。我需要基于反馈的个性化推荐。

Argos 通过多源聚合、Board 系统、LLM 质量评分、结构化摘要生成、RAG 深度对话、个性化推荐这些核心功能来解决这些问题。

---

### Q3: 这个项目的难点在哪里？

**回答**：

我认为有三个主要难点：

**第一是 RAG 管道的设计**。一个完整的 RAG 系统涉及很多环节：网页抓取、正文提取、文本分块、向量化、检索、重排序、生成。每个环节都有坑。比如正文提取，很多网站有反爬机制，或者正文被大量广告和导航栏污染。我用了 trafilatura 作为主要提取器，BeautifulSoup 作为兜底，还设计了内容质量评估算法来检测噪声。

**第二是个性化推荐的冷启动问题**。新用户没有反馈历史，如何做个性化？我的方案是多层次的：显式偏好（用户手动设置关注/屏蔽话题）可以立即生效；隐式反馈（点赞/点踩）需要积累；同时系统会记录每次对话，未来可以做对话级别的兴趣推断。

**第三是成本控制**。LLM API 调用是有成本的。我通过 Redis 缓存 RSS 结果（15分钟）、SQLite 缓存历史简报、ChromaDB 缓存向量，尽量减少重复调用。同时设计了质量评分机制，先对文章打分，只对高质量文章做摘要生成，避免浪费 token。

---

## 架构设计类问题

### Q4: 请画出系统的整体架构图

**回答**：

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (Jinja2 + Vanilla JS)               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │Dashboard │ │RAG Panel │ │ History  │ │ Insights │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │  Router  │ │RAG Router│ │  Static  │ │   SSE    │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Service Layer                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │RSS Service│ │LLM Service│ │RAG Service│ │Learning  │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │DB Service│ │Email Svc │ │Redis Svc │ │Insights  │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data Layer                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │  SQLite  │ │ ChromaDB │ │  Redis   │ │DeepSeek  │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

分层设计的好处是职责清晰、易于测试、便于扩展。比如未来要换向量数据库，只需要修改 RAG Service，不影响上层。

---

### Q5: 为什么选择 SQLite 而不是 PostgreSQL？

**回答**：

这是一个有意为之的设计决策，基于以下考虑：

**1. 部署简单**：SQLite 是嵌入式数据库，无需单独部署数据库服务，一个文件就是一个数据库。对于个人项目或小团队，这大大降低了运维成本。

**2. 性能足够**：Argos 是读多写少的场景（每天只生成一份简报），SQLite 的读性能完全可以满足需求。我使用了异步驱动 aiosqlite，避免阻塞事件循环。

**3. 数据量可控**：系统默认只保留 7 天历史，数据量不会无限增长。SQLite 在百万级数据下表现良好。

**4. 便于备份**：一个 db 文件，直接复制即可备份。

如果未来出现高并发或数据量大幅增长，迁移到 PostgreSQL 是合理的。当前产品边界仍是私有单用户/小型自托管，不把多用户或多租户作为默认演进路线。

---

### Q6: 为什么选择 ChromaDB 作为向量数据库？

**回答**：

选择 ChromaDB 主要基于以下考虑：

**1. 零运维**：ChromaDB 是嵌入式向量数据库，无需单独部署服务，数据存储在本地文件系统。这与 SQLite 的设计理念一致。

**2. 功能完整**：支持 HNSW 索引、元数据过滤、持久化存储，满足 RAG 场景的核心需求。

**3. Python 友好**：原生 Python 实现，API 简洁，与 FastAPI 集成顺畅。

**4. 性能足够**：对于单机部署、百万级向量的场景，ChromaDB 的查询延迟在可接受范围内。

**局限性**：ChromaDB 不支持分布式部署，如果未来需要横向扩展，会考虑迁移到 Qdrant 或 Milvus。我在设计时已经做了抽象层（`_collection_name_for`、`delete_collections_by_urls` 等函数），迁移成本可控。

---

### Q7: Redis 在系统中的作用是什么？

**回答**：

Redis 在系统中有三个主要用途：

**1. RSS 缓存**：RSS 源的响应缓存 15 分钟，避免频繁请求同一源。这对于有请求限制的 RSS 源尤其重要。

```python
cache_key = f"rss_feed_{url}"
cached_data = await redis_service.get_cache(cache_key)
if cached_data:
    return RSSResponse(**cached_data)
```

**2. Token 消耗统计**：记录每日 LLM API 的 token 消耗，用于成本监控。

```python
await client.hincrby(key, "prompt_tokens", prompt)
await client.hincrby(key, "completion_tokens", completion)
```

**3. 延迟监控**：记录简报生成的延迟数据，计算 P50/P99。

```python
await client.rpush(key, str(duration_sec))
```

Redis 不是必需的——如果连接失败，系统会降级运行（跳过缓存，直接请求）。这保证了系统的健壮性。

---

## RAG 技术类问题

### Q8: 请详细介绍一下 RAG 管道的设计

**回答**：

RAG 管道分为两个阶段：摄入（Ingest）和查询（Query）。

**摄入阶段**：

```
URL → 安全检查 → 网页抓取 → 正文提取 → 质量评估 → 分块 → 向量化 → 存储
```

1. **安全检查**：阻止访问内网地址（localhost、私有 IP），防止 SSRF 攻击。

2. **网页抓取**：使用 httpx 异步请求，支持重定向跟踪，自定义 User-Agent。

3. **正文提取**：优先使用 trafilatura（基于机器学习的高精度提取器），失败时用 BeautifulSoup 兜底。

4. **质量评估**：检测噪声词比例、段落密度、文本长度，输出质量评分。

5. **分块**：按句子边界分割，每块最多 600 字符，重叠 100 字符保持上下文连贯。

6. **向量化**：使用 BAAI/bge-m3 模型生成 1024 维向量。

7. **存储**：存入 ChromaDB，每个 URL 对应一个 Collection。

**查询阶段**：

```
问题 → HyDE改写 → 混合检索 → RRF融合 → Cross-Encoder重排 → 个性化加权 → LLM生成
```

1. **HyDE 改写**：让 LLM 生成假设性回答，将问题和假设回答的向量取平均，增强语义召回。

2. **混合检索**：
   - Bi-Encoder 向量召回（语义相似）
   - BM25 关键词召回（精确匹配）
   
3. **RRF 融合**：使用 Reciprocal Rank Fusion 算法合并两个召回结果。

4. **Cross-Encoder 重排**：对融合后的候选进行精排，取 Top-3。

5. **个性化加权**：根据用户反馈历史调整分数。

6. **LLM 生成**：将 Top-3 chunks 作为上下文，流式生成回答。

---

### Q9: 为什么选择混合检索而不是纯向量检索？

**回答**：

纯向量检索有局限性，混合检索可以互补：

**向量检索的优势**：
- 语义理解能力强，"苹果手机"和"iPhone"可以匹配
- 对同义词、近义词友好

**向量检索的劣势**：
- 对专有名词、型号、代码片段可能失真
- 对精确匹配（如"Python 3.11"）不如关键词

**BM25 的优势**：
- 精确匹配，对专有名词、代码片段友好
- 可解释性强

**BM25 的劣势**：
- 无法理解语义，"AI"和"人工智能"无法关联

混合检索结合两者优势，通过 RRF 融合：

```python
# RRF 公式
RRF_score(d) = Σ 1/(k + rank(d))  # k=60 是标准常数
```

实际效果：对于"OpenAI 发布了什么新模型？"这类问题，向量检索能理解语义；对于"GPT-4 的上下文窗口是多少？"这类精确问题，BM25 更准确。融合后两者都能覆盖。

---

### Q10: HyDE 是什么？为什么使用它？

**回答**：

HyDE（Hypothetical Document Embedding）是一种查询改写技术，核心思想是：**让 LLM 先生成一个假设性回答，然后用这个假设回答的向量来检索**。

**原理**：

用户的问题往往很短、很模糊，直接用问题向量检索效果不佳。但 LLM 生成的假设回答包含了更多语义信息，用假设回答检索可以找到更相关的文档。

**示例**：

```
问题："Transformer 是什么？"

假设回答："Transformer 是一种基于自注意力机制的神经网络架构，
由 Google 在 2017 年的论文《Attention Is All You Need》中提出。
它彻底改变了 NLP 领域，是 BERT、GPT 等模型的基础架构..."

检索：用假设回答的向量去检索，而不是用"Transformer 是什么"这个短问题
```

**实现**：

```python
async def _hyde_rewrite(question: str) -> str:
    prompt = f"请直接给出一段简短的假设性回答（50-100字）：\n\n问题：{question}"
    response = await client.chat.completions.create(...)
    return response.choices[0].message.content

# 向量融合
raw_embs = bi_encoder.encode([question, hyde_text])
q_embedding = (raw_embs[0] + raw_embs[1]) / 2
```

**权衡**：HyDE 会增加一次 LLM 调用（成本和延迟），所以我在配置中设置了开关 `RAG_HYDE_ENABLED`，可以根据场景决定是否启用。

---

### Q11: Cross-Encoder 和 Bi-Encoder 有什么区别？为什么两者都用？

**回答**：

**Bi-Encoder（双塔模型）**：
- 将问题和文档分别编码成向量
- 相似度通过向量点积计算
- 优点：可以预先计算文档向量，检索速度快
- 缺点：问题和文档在编码时互不感知，精度有限

**Cross-Encoder（交叉编码器）**：
- 将问题和文档拼接后一起输入模型
- 模型直接输出相似度分数
- 优点：问题和文档可以深度交互，精度高
- 缺点：无法预先计算，每次查询都要重新计算，速度慢

**为什么两者都用？**

这是一个经典的"召回-排序"两阶段设计：

```
第一阶段（召回）：Bi-Encoder
- 从 10000 个文档中快速召回 Top-20
- 时间复杂度：O(N) 向量搜索

第二阶段（排序）：Cross-Encoder
- 对 Top-20 进行精排，取 Top-3
- 时间复杂度：O(20) 次模型推理
```

如果只用 Cross-Encoder，每次查询要对 10000 个文档做推理，延迟不可接受。如果只用 Bi-Encoder，精度不够。两者结合，既保证了效率，又保证了精度。

---

### Q12: 如何处理网页抓取中的反爬机制？

**回答**：

网页抓取确实有很多坑，我的处理策略包括：

**1. 自定义 User-Agent**：

```python
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/"
}
```

很多网站会屏蔽默认的 Python User-Agent，伪装成浏览器可以绑过基础检测。

**2. 重定向跟踪**：

```python
for _ in range(redirect_limit + 1):
    response = await client.get(current_url)
    if response.is_redirect:
        location = response.headers.get("location")
        current_url = urljoin(str(response.url), location)
        continue
```

很多短链接、跳转链接需要手动跟踪。

**3. 正文提取容错**：

```python
# 优先 trafilatura
text = trafilatura.extract(html_content, ...)

# 失败时用 BeautifulSoup 兜底
if not text or len(text) < 300:
    soup = BeautifulSoup(html_content, "html.parser")
    # 移除噪声标签
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
```

**4. 质量评估**：

即使成功抓取，内容质量也可能很差（广告多、正文短）。我设计了质量评估算法：

```python
def assess_content_quality(text: str) -> dict:
    # 段落密度
    meaningful_lines = [line for line in lines if len(line) > 30]
    density = len(meaningful_lines) / total_lines
    
    # 噪声词比例
    noise_hits = len(_NOISE_PATTERNS.findall(text))
    noise_ratio = noise_hits / total_lines
    
    # 综合评分
    score = (density * 0.45) + ((1 - noise_ratio) * 0.25) + (length_score * 0.30)
```

**5. 优雅降级**：

如果抓取失败或质量太差，系统不会崩溃，而是返回错误信息，让用户知道这篇文章暂时无法分析。

---

### Q13: 文本分块策略是怎样的？为什么这样设计？

**回答**：

分块是 RAG 系统的关键环节，我的策略是**基于句子边界的滑动窗口**：

```python
def split_into_chunks(text: str, max_chars: int = 600, overlap: int = 100):
    # 按句子分割
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)
    
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) <= max_chars:
            current_chunk += sentence + " "
        else:
            chunks.append(current_chunk.strip())
            # 新块携带上一块的末尾作为上下文
            current_chunk = current_chunk[-overlap:] + sentence + " "
    
    return chunks
```

**设计考量**：

1. **为什么 600 字符？**
   - 太小：上下文不完整，检索效果差
   - 太大：包含太多无关信息，干扰 LLM
   - 600 字符大约是 1-2 个段落，平衡了完整性和精确性

2. **为什么 100 字符重叠？**
   - 保证跨块的语义连贯
   - 避免关键信息被截断在块边界

3. **为什么按句子分割？**
   - 避免在句子中间截断，保持语义完整
   - 正则 `(?<=[。！？.!?])` 匹配中英文句末标点

**改进空间**：

当前策略是通用的，未来可以针对不同类型文章优化：
- 技术文档：按章节/标题分割
- 代码相关：按函数/类分割
- 新闻文章：当前策略已经足够

---

## LLM 应用类问题

### Q14: 如何保证 LLM 输出的结构化？

**回答**：

我使用了 OpenAI SDK 的 `response_format` 参数：

```python
response = await self.client.chat.completions.create(
    model="deepseek-chat",
    messages=[...],
    response_format={"type": "json_object"},  # 强制 JSON 输出
    temperature=0.3
)
```

这会强制模型输出有效的 JSON。但仅有这个不够，还需要：

**1. Prompt 中明确指定 Schema**：

```
Output JSON schema must strictly match:
{
  "date": "YYYY-MM-DD",
  "overview": "A 2-3 sentence summary...",
  "top_news": [
    {
      "headline": "...",
      "category": "...",
      "key_points": ["...", "..."],
      "tags": ["#Tag1", "#Tag2"],
      "original_link": "...",
      "source": "..."
    }
  ]
}
```

**2. 低温度采样**：

`temperature=0.3` 降低随机性，让输出更稳定。

**3. Pydantic 验证**：

```python
parsed_json = json.loads(response.choices[0].message.content)
return DailySummaryResponse(**parsed_json)  # Pydantic 会验证字段
```

如果字段缺失或类型错误，Pydantic 会抛出异常，系统会记录日志并返回错误。

---

### Q15: LLM 质量评分是如何实现的？

**回答**：

质量评分是在摘要生成之前的一个预筛选步骤：

```python
async def _score_articles(self, articles: list[dict]) -> tuple[list[dict], dict]:
    scoring_prompt = """你是一个新闻质量评估员。
    
    对每篇文章，从以下维度打分（1-10）：
    - 与科技/AI/编程的相关性
    - 新闻价值（非广告、非公关稿）
    - 教育或讨论价值
    
    输出 JSON：{"scores": [{"index": 0, "score": 8}, ...]}
    """
    
    input_for_scoring = json.dumps([
        {"index": i, "title": a["title"], "summary": a["summary"][:150]}
        for i, a in enumerate(articles)
    ])
    
    response = await self.client.chat.completions.create(...)
    scores = json.loads(response.choices[0].message.content)["scores"]
    
    # 过滤低质量文章（阈值 5 分）
    high_quality = [a for i, a in enumerate(articles) 
                    if scores[i]["score"] >= 5]
    
    return high_quality, report
```

**设计考量**：

1. **为什么先评分再生成？**
   - 成本控制：评分只需要文章标题和摘要，token 消耗少
   - 生成摘要需要完整内容，token 消耗大
   - 先过滤再生成，可以节省大量 token

2. **阈值为什么是 5？**
   - 之前是 7 分，但发现过滤太严格，导致简报内容不够丰富
   - 调整为 5 分后，可以保留更多有价值的文章
   - 同时确保最终输出 8-12 篇文章

3. **兜底机制**：
   - 如果过滤后文章太少（<8篇），会取评分最高的 10 篇
   - 避免因为评分失误导致无内容可展示

4. **文章去重**：
   - 生成简报前，排除过去 3 天已展示的文章
   - 避免用户连续几天看到相同内容

5. **多样性控制**：
   - 用户偏好最多只影响 30-40% 的文章
   - 防止信息茧房，确保用户能看到多样化的内容

---

### Q16: Persona 是如何注入到 LLM 的？

**回答**：

Persona 注入是在 System Prompt 中实现的：

```python
def generate_daily_summary(self, rss_responses, session, one_time_preference):
    # 1. 从数据库获取用户偏好
    personas = await db_service.get_active_personas(session)
    
    # 2. 构建偏好上下文
    persona_context = "\n\nUSER PERSONALITY & PREFERENCE GUIDELINES:\n"
    for persona in personas:
        if persona.category == "instruction":
            marker = "[Instruction]"
        elif persona.category == "focus_topic":
            marker = "[MUST COVER topic]"
        elif persona.category == "block_topic":
            marker = "[NEVER include topic]"
        # ... 其他类型
        
        persona_context += f"- {marker} {persona.content}\n"
    
    # 3. 注入到 System Prompt
    messages = [
        {"role": "system", "content": EDITOR_PROMPT + persona_context},
        {"role": "user", "content": input_json}
    ]
```

**效果示例**：

```
System: You are the Chief Editor of "Argos"...

USER PERSONALITY & PREFERENCE GUIDELINES:
- [Instruction] 多关注 AI 大模型进展
- [MUST COVER topic] GPT, Claude, LLaMA
- [NEVER include topic] 股市行情
- [Preferred source] Ars Technica
- [De-prioritize source] 某某营销号

Strictly adhere to these preferences while selecting and summarizing.
```

这样 LLM 在生成摘要时会遵循用户的偏好。

---

### Q17: 如何处理 LLM 调用的成本和延迟？

**回答**：

**成本控制**：

1. **多级缓存**：
   - Redis 缓存 RSS 结果（15分钟）
   - SQLite 缓存历史简报（永久）
   - ChromaDB 缓存向量（永久）
   - 内存缓存文章正文（LRU，256 条）

2. **质量预筛选**：
   - 先用少量 token 对文章评分
   - 只对高质量文章（≥5分）生成摘要
   - 确保最终输出 8-12 篇文章

3. **文章去重**：
   - 生成简报前排除过去 3 天已展示的文章
   - 避免重复生成相同内容的摘要

4. **Token 统计**：
   ```python
   await metrics_service.record_tokens(
       response.usage.prompt_tokens,
       response.usage.completion_tokens
   )
   ```
   每日统计消耗，便于成本监控。

**延迟优化**：

1. **流式输出**：
   ```python
   stream = await client.chat.completions.create(
       model="deepseek-chat",
       messages=[...],
       stream=True,
       stream_options={"include_usage": True}
   )
   
   async for chunk in stream:
       if chunk.choices[0].delta.content:
           yield chunk.choices[0].delta.content
   ```
   用户可以实时看到输出，感知延迟更低。

2. **后台摄入**：
   - 文章向量化在后台 Worker 中异步进行
   - 不阻塞主请求

3. **并发请求**：
   - RSS 抓取使用 `asyncio.gather` 并发
   - 多个 Worker 并行处理摄入任务

---

## 数据库与存储类问题

### Q18: 如何避免用户看到重复的文章？

**回答**：

我实现了文章去重机制，在生成简报时排除过去 3 天已展示的文章：

**1. 数据库查询**：

```python
async def get_recent_article_urls(
    self,
    session: AsyncSession,
    days: int = 3,
) -> set[str]:
    """
    返回过去 N 天（不含今天）已展示的文章 URL
    """
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    # 查询过去 3 天的摘要
    stmt = select(DailySummary.id).where(
        DailySummary.date >= cutoff,
        DailySummary.date < today
    )
    summary_ids = (await session.execute(stmt)).scalars().all()
    
    # 查询这些摘要中的文章 URL
    news_stmt = select(NewsItem.original_link).where(
        NewsItem.summary_id.in_(summary_ids)
    )
    return set((await session.execute(news_stmt)).scalars().all())
```

**2. 生成时过滤**：

```python
# 在 LLM 服务中
recent_urls = await db_service.get_recent_article_urls(session, days=3)
raw_articles = [a for a in raw_articles if a["link"] not in recent_urls]
logger.info("Dedup: removed %d articles already shown recently", removed_count)
```

**设计考量**：

- **为什么是 3 天？** 科技资讯的时效性通常在 3-5 天，超过 3 天的文章可以重新出现
- **为什么不含今天？** 避免同一天多次生成时互相干扰
- **容错处理**：如果查询失败，跳过去重继续生成，不影响用户体验

---

### Q19: 如何防止信息茧房？

**回答**：

信息茧房是个性化推荐系统的常见问题。我的解决方案是**限制用户偏好的影响范围**：

**1. Prompt 层面控制**：

```
IMPORTANT: These preferences should influence article PRIORITY
(put preferred topics near the top), but do NOT let them dominate
the entire briefing. At most 30-40% of articles should match user
interests — the rest should cover other important news of the day
for breadth.
```

**2. 多样性要求**：

在 System Prompt 中明确要求：
- 输出 8-12 篇文章
- 确保分类和来源的多样性
- 不要过度代表单一话题

**3. 质量评分独立**：

质量评分是基于文章本身的价值，而非用户偏好。即使用户偏好 AI，一篇关于硬件的高质量文章仍然会被选中。

**4. 显式偏好 vs 隐式反馈**：

- 显式偏好（关注话题）影响排序，但不排除其他内容
- 隐式反馈（点赞）用于重排序，但权重有限

**效果**：

用户会看到自己感兴趣的内容排在前面，但仍然能了解到当天其他重要的科技新闻，保持信息摄入的多样性。

---

### Q20: 数据库表是如何设计的？为什么这样设计？

**回答**：

核心表有 5 个：

```
DailySummary (1) ←→ (N) NewsItem
     ↓
UserFeedback (文章级反馈)
UserPersona (用户偏好指令)
ChatMessage (RAG对话历史)
```

**设计考量**：

1. **DailySummary 和 NewsItem 分离**：
   - 摘要和新闻是 1:N 关系
   - 分离存储便于独立查询和更新
   - 级联删除保证数据一致性

2. **UserFeedback 用 article_url 做唯一键**：
   - 一篇文章只能有一条反馈
   - 避免重复反馈导致数据污染
   - 代码中有去重逻辑处理历史遗留问题

3. **UserPersona 的 category 字段**：
   - 支持多种偏好类型：instruction、focus_topic、block_topic 等
   - 便于细粒度控制

4. **ChatMessage 按 article_url 索引**：
   - 快速查询某篇文章的对话历史
   - 支持多轮对话上下文

**改进空间**：

当前设计刻意保持单用户边界。这样可以把部署、备份、权限和数据模型都维持在自托管可维护的复杂度内；多用户或租户隔离不属于当前产品目标。

---

### Q21: 如何处理数据清理？

**回答**：

数据清理由 APScheduler 定时执行，每 6 小时一次：

```python
async def cleanup_old_data(session, days_to_keep=7):
    # 1. 找到过期摘要
    threshold_date = (datetime.now() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
    old_summaries = await session.execute(
        select(DailySummary).where(DailySummary.date < threshold_date)
    )
    
    # 2. 提取关联的文章 URL
    urls_to_delete = await session.execute(
        select(NewsItem.original_link).where(NewsItem.summary_id.in_(summary_ids))
    )
    
    # 3. 删除向量数据
    await delete_collections_by_urls(urls_to_delete)
    
    # 4. 删除反馈和聊天记录
    await session.execute(delete(UserFeedback).where(...))
    await session.execute(delete(ChatMessage).where(...))
    
    # 5. 删除摘要（级联删除 NewsItem）
    for summary in old_summaries:
        await session.delete(summary)
```

**为什么是 7 天？**

- 科技资讯时效性强，7 天前的新闻价值大幅降低
- 控制数据量，避免无限增长
- 可通过 `HISTORY_DAYS_TO_KEEP` 配置调整

**为什么每 6 小时而不是每天？**

- 避免一次性删除大量数据导致性能抖动
- 更频繁的清理保持系统轻量

---

### Q22: ChromaDB 的 Collection 是如何组织的？

**回答**：

每个文章 URL 对应一个独立的 Collection：

```python
def _collection_name_for(url: str) -> str:
    # 生成安全的 Collection 名称
    safe = re.sub(r"[^a-zA-Z0-9]", "-", url)[-52:]
    return f"rag-m3-{safe}"

# 示例
# URL: https://techcrunch.com/2024/01/15/gpt-5-announcement
# Collection: rag-m3-techcrunch-com-2024-01-15-gpt-5-announcement
```

**为什么一个 URL 一个 Collection？**

1. **隔离性**：不同文章的向量互不干扰
2. **清理方便**：删除文章时直接删除整个 Collection
3. **查询精确**：查询时只搜索目标文章的 Collection

**元数据存储**：

```python
collection = _chroma_client.create_collection(
    name=collection_name,
    metadata={"url": url}  # 存储 URL 便于反向查找
)
```

**启动时恢复**：

```python
# 应用启动时，遍历所有 Collection，恢复 _ingested_urls 映射
for coll_obj in _chroma_client.list_collections():
    if coll_obj.name.startswith("rag-m3-"):
        metadata = coll_obj.metadata
        if metadata and "url" in metadata:
            _ingested_urls[metadata["url"]] = coll_obj.name
```

---

## 性能优化类问题

### Q23: 系统有哪些性能优化措施？

**回答**：

**1. 异步 I/O**：

全链路异步，避免阻塞：
- httpx 异步 HTTP 客户端
- aiosqlite 异步数据库
- AsyncOpenAI 异步 LLM 调用

**2. 多级缓存**：

| 层级 | 存储 | 内容 | TTL |
|------|------|------|-----|
| L1 | 内存 LRU | 文章正文、概览 | 无限（LRU 淘汰） |
| L2 | Redis | RSS 响应 | 15 分钟 |
| L3 | SQLite | 历史简报 | 永久 |
| L4 | ChromaDB | 文章向量 | 永久 |

**3. 并发处理**：

```python
# RSS 抓取并发
tasks = [fetch_and_parse_feed(url, client) for url in urls]
results = await asyncio.gather(*tasks)

# 后台摄入多 Worker
for i in range(settings.RAG_BACKGROUND_INGEST_WORKERS):
    task = asyncio.create_task(ingest_worker_loop(worker_id=i))
```

**4. 流式响应**：

- RAG 问答使用 SSE 流式输出
- 用户感知延迟更低

**5. 懒加载**：

- Bi-Encoder 和 Cross-Encoder 使用 `@lru_cache` 延迟加载
- 首次使用时才加载模型

**6. 数据清理**：

- 定期清理过期数据，控制数据量

---

### Q24: 如何监控系统性能？

**回答**：

**1. 结构化日志**：

使用 structlog，每条日志包含：
- timestamp（ISO-8601）
- level（日志级别）
- logger（模块名）
- trace_id（请求追踪 ID）

```python
logger.info("Background ingested %s (%d chunks)", url, result["chunks"])
```

**2. TraceID 追踪**：

```python
class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        tid = new_trace_id()  # 生成 12 位 hex
        response = await call_next(request)
        response.headers["X-Trace-ID"] = tid
        return response
```

每个请求有唯一 ID，便于在日志中追踪。

**3. Token 消耗统计**：

```python
# Redis Hash 存储
key = f"metrics:tokens:{date}"
await client.hincrby(key, "prompt_tokens", prompt)
await client.hincrby(key, "completion_tokens", completion)
await client.hincrby(key, "total_tokens", prompt + completion)
```

**4. 延迟监控**：

```python
# Redis List 存储
key = f"metrics:latency:summary:{date}"
await client.rpush(key, str(duration_sec))

# 计算 P50/P99
latencies = [float(x) for x in await client.lrange(key, 0, -1)]
p50 = statistics.median(latencies)
p99 = statistics.quantiles(latencies, n=100)[-1]
```

**5. 前端展示**：

偏好面板中展示今日系统消耗：
- 消耗 Tokens
- 简报耗时 P50/P99

---

### Q25: 如果用户量增大，系统如何扩展？

**回答**：

**当前架构的瓶颈**：

1. SQLite：单文件数据库，无法横向扩展
2. ChromaDB：嵌入式向量库，无法分布式
3. 内存缓存：单机内存有限
4. 同步 LLM 调用：受限于 API 速率限制

**扩展方案**：

**短期（10x 用户量）**：

1. **SQLite → PostgreSQL**：
   - SQLModel 抽象层让迁移成本低
   - 支持连接池、读写分离

2. **Redis 集群**：
   - 缓存层横向扩展

3. **LLM 调用限流**：
   - 实现令牌桶限流
   - 避免触发 API 速率限制

**中期（100x 用户量）**：

1. **ChromaDB → Qdrant/Milvus**：
   - 分布式向量数据库
   - 支持横向扩展

2. **消息队列**：
   - 引入 Celery/RQ 处理后台任务
   - 解耦摄入和查询

3. **CDN + 静态化**：
   - 历史简报静态化
   - 减少数据库查询

**长期（1000x 用户量）**：

1. **微服务拆分**：
   - RSS 服务、LLM 服务、RAG 服务独立部署
   - 各自扩展

2. **自托管运维加固**：
   - 更清晰的备份/恢复与故障诊断
   - 更稳健的单实例部署和反向代理文档

3. **多区域部署**：
   - 就近访问
   - 数据同步

---

## 系统设计类问题

### Q26: 如果让你重新设计这个系统，会有什么不同？

**回答**：

**会保留的设计**：

1. **分层架构**：Service Layer 的抽象让系统易于维护和扩展
2. **混合检索**：向量 + BM25 的融合效果确实好
3. **流式输出**：用户体验提升明显
4. **多级缓存**：成本控制的关键

**会改进的设计**：

1. **更早引入消息队列**：
   - 当前后台摄入用 asyncio.Queue，重启会丢失
   - 应该用 Redis Stream 或 RabbitMQ 持久化

2. **更完善的测试**：
   - 当前测试覆盖率不够
   - 应该有更多单元测试和集成测试

3. **配置中心化**：
   - RSS 源硬编码在配置中
   - 应该支持动态管理（数据库存储）

4. **监控告警**：
   - 当前只有日志和基础指标
   - 应该接入 Prometheus + Grafana，配置告警规则

5. **API 版本管理**：
   - 当前 `/api/v1` 是硬编码
   - 应该有更规范的版本管理策略

---

### Q27: 如何保证系统的安全性？

**回答**：

**1. SSRF 防护**：

```python
async def ensure_public_url_target(url: str) -> str:
    # 检查协议
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Invalid protocol")
    
    # 检查主机名
    if host in {"localhost"} or host.endswith(".local"):
        raise ValueError("Blocked host")
    
    # DNS 解析后检查 IP
    results = await loop.getaddrinfo(host, port, ...)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback:
            raise ValueError("Private IP blocked")
```

防止攻击者通过 RAG 接口访问内网资源。

**2. 输入验证**：

```python
class QueryRequest(PublicUrlRequest):
    question: str = Field(min_length=1)

@field_validator("url")
def validate_url(cls, value):
    return validate_public_url(value)
```

Pydantic 自动验证输入，防止注入攻击。

**3. CORS 配置**：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.C{}
ORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

限制允许的来源，防止跨站请求伪造。

**4. 敏感信息保护**：

- API Key 通过环境变量配置，不硬编码
- `.env` 文件在 `.gitignore` 中
- 日志中不输出敏感信息

**5. HTTPS**：

生产环境强制 HTTPS，防止中间人攻击。

**改进空间**：

- 添加 Rate Limiting，防止 API 滥用
- 添加认证机制（当前是公开 API）
- 添加输入内容过滤，防止恶意 Prompt 注入

---

### Q28: 系统的可观测性如何设计？

**回答**：

可观测性包括三个支柱：日志、指标、追踪。

**1. 日志（Logging）**：

使用 structlog 实现结构化日志：

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_trace_id,  # 注入 TraceID
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()  # JSON 输出
    ]
)
```

每条日志是一个 JSON 对象，便于 ELK/Loki 采集和分析。

**2. 指标（Metrics）**：

自定义指标存储在 Redis：

```python
# Token 消耗
metrics:tokens:{date} → {prompt_tokens, completion_tokens, total_tokens}

# 延迟分布
metrics:latency:summary:{date} → [8.5, 9.2, 7.8, ...]
```

通过 `/api/v1/metrics` 接口暴露。

**改进**：应该接入 Prometheus，使用标准格式暴露指标。

**3. 追踪（Tracing）**：

通过 TraceID 实现请求追踪：

```python
# 中间件生成 TraceID
class TraceIDMiddleware:
    async def dispatch(self, request, call_next):
        tid = uuid.uuid4().hex[:12]
        trace_id_ctx.set(tid)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = tid
        return response

# 日志自动注入 TraceID
def _add_trace_id(logger, method_name, event_dict):
    event_dict["trace_id"] = trace_id_ctx.get("-")
    return event_dict
```

**改进**：应该接入 OpenTelemetry，实现分布式追踪。

---

### Q29: 如何处理并发请求？

**回答**：

**1. 异步架构**：

FastAPI 原生支持异步，使用 asyncio 事件循环处理并发：

```python
# 并发抓取 RSS
tasks = [fetch_and_parse_feed(url, client) for url in urls]
results = await asyncio.gather(*tasks)
```

**2. 数据库连接池**：

```python
engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    connect_args={"check_same_thread": False}  # SQLite 多线程
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
```

每个请求从连接池获取连接，用完归还。

**3. 简报生成锁**：

避免同一时间多个请求生成同一份简报：

```python
_summary_generation_lock = asyncio.Lock()

async def generate_summary(...):
    async with _summary_generation_lock:
        # 双重检查
        existing = await db_service.get_summary_by_date(session, date)
        if existing:
            return existing
        
        # 生成简报
        summary = await llm_service.generate_daily_summary(...)
```

**4. 后台任务队列**：

```python
_ingest_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

async def ingest_worker_loop(worker_id: int):
    while True:
        url = await _ingest_queue.get()
        if url is None:  # 关闭信号
            return
        await ingest(url)
```

多个 Worker 并行处理摄入任务。

---

## 工程实践类问题

### Q30: 项目的测试策略是什么？

**回答**：

当前项目有基础测试，但覆盖率不够。理想的测试策略应该是：

**1. 单元测试**：

```python
# 测试分块函数
def test_split_into_chunks():
    text = "这是第一句。这是第二句。这是第三句。"
    chunks = split_into_chunks(text, max_chars=20, overlap=5)
    assert len(chunks) == 3
    assert "第一句" in chunks[0]

# 测试质量评估
def test_assess_content_quality():
    text = "这是一篇高质量的技术文章..." * 50
    result = assess_content_quality(text)
    assert result["verdict"] == "good"
    assert result["score"] > 0.6
```

**2. 集成测试**：

```python
@pytest.mark.asyncio
async def test_rag_pipeline():
    # 摄入
    result = await ingest("https://example.com/article")
    assert result["chunks"] > 0
    
    # 查询
    responses = []
    async for token in query_stream("文章讲了什么？", url):
        responses.append(token)
    
    assert len(responses) > 0
```

**3. API 测试**：

```python
def test_summary_endpoint(client):
    response = client.get("/api/v1/summary")
    assert response.status_code == 200
    data = response.json()
    assert "date" in data
    assert "top_news" in data
```

**改进计划**：

- 使用 pytest-cov 统计覆盖率
- 目标覆盖率 80%+
- 添加 CI 自动运行测试

---

### Q31: 如何管理项目依赖？

**回答**：

**1. requirements.txt**：

明确指定版本范围：

```
fastapi>=0.111.0
uvicorn[standard]>=0.30.1
pydantic>=2.7.4
```

**2. pyproject.toml**：

配置项目元数据和工具：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**3. 虚拟环境**：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**改进**：

- 应该使用 `pip-tools` 或 Poetry 精确锁定版本
- 生成 `requirements.lock` 确保可复现

---

### Q32: 项目的部署流程是怎样的？

**回答**：

**Docker 部署（推荐）**：

```yaml
# docker-compose.yml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
    volumes:
      - ./data:/app/data
    depends_on:
      - redis
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

```bash
# 部署步骤
cp .env.template .env
vim .env  # 配置 API Key
docker compose up -d
```

**本地开发**：

```bash
# Windows 一键启动
scripts\Open_Web_Dashboard.bat

# 或手动启动
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

**生产环境建议**：

1. 使用 Gunicorn + Uvicorn Workers
2. 配置 Nginx 反向代理
3. 启用 HTTPS
4. 配置日志采集（ELK/Loki）
5. 配置监控告警（Prometheus + Grafana）

---

### Q33: 你从这个项目中学到了什么？

**回答**：

**技术层面**：

1. **RAG 系统的复杂性**：从理论到实践，深刻理解了检索增强生成的每个环节。特别是混合检索、重排序、HyDE 这些技术，书本上看到和实际实现是两回事。

2. **异步编程**：Python asyncio 的最佳实践，如何避免阻塞事件循环，如何处理并发。

3. **LLM 应用开发**：Prompt Engineering、结构化输出、流式响应、成本控制。

**工程层面**：

1. **系统设计**：如何做分层架构、如何设计数据模型、如何做扩展性考虑。

2. **可观测性**：日志、指标、追踪的重要性，出了问题如何快速定位。

3. **权衡取舍**：SQLite vs PostgreSQL、ChromaDB vs Qdrant、成本 vs 性能，每个决策都有 trade-off。

**产品层面**：

1. **用户视角**：从自己的痛点出发，设计真正有用的功能。

2. **迭代思维**：先做 MVP，再逐步完善。不要一开始就追求完美。

---

### Q34: 如果面试官问你"还有什么想说的"，你会说什么？

**回答**：

Argos 是我真正投入心血的一个项目。它不是简单的 Demo，而是一个完整的、可运行的产品。

从技术角度，它覆盖了现代 AI 应用的核心技术栈：LLM、RAG、向量数据库、异步编程、缓存策略。每个技术选型都有深思熟虑的理由，每个设计决策都有权衡考量。

从产品角度，它解决了我自己的真实痛点。我自己每天都在用这个系统追踪科技资讯，也在根据使用体验持续优化。

当然，项目还有很多可以改进的地方：测试覆盖率、监控告警、自托管运维体验、更完善的错误处理。这些都是我未来迭代的方向。

如果有机会加入贵公司，我希望能够把这些实践经验带到工作中，同时也期待在更大的平台上学习和成长。

---

## 总结

这份面试问答覆盖了 Argos 项目的方方面面，共 **34 个问题**：

| 类别 | 问题数 | 核心内容 |
|------|--------|----------|
| 项目概述类 | 3 | 项目介绍、痛点、难点 |
| 架构设计类 | 4 | 架构图、SQLite/ChromaDB/Redis 选型理由 |
| RAG 技术类 | 6 | 管道设计、混合检索、HyDE、Cross-Encoder、反爬处理、分块策略 |
| LLM 应用类 | 4 | 结构化输出、质量评分、Persona 注入、成本延迟优化 |
| 数据库与存储类 | 5 | 表设计、文章去重、信息茧房防护、数据清理、ChromaDB 组织 |
| 性能优化类 | 3 | 优化措施、性能监控、扩展方案 |
| 系统设计类 | 4 | 重新设计、安全性、可观测性、并发处理 |
| 工程实践类 | 5 | 测试策略、依赖管理、部署流程、项目收获、总结陈词 |

**新增内容亮点**：

- **Q18: 如何避免用户看到重复的文章？** - 文章去重机制详解
- **Q19: 如何防止信息茧房？** - 多样性控制策略

希望这份文档能帮助你更好地理解和展示这个项目。

---

*最后更新：2026年4月28日*
