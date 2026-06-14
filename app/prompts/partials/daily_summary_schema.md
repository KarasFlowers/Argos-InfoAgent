---
key: daily_summary_schema
name: 日报输出 JSON Schema
type: partial
user_selectable: false
version: "1.1.0"
description: 日报 summary 的统一 JSON 输出格式要求，被所有 board_summary 模板引用
---

## 输出格式（强制）

你必须输出一个**合法 JSON 对象**，严格匹配下方 schema。禁止：
- 在 JSON 外添加任何文字、解释或代码块标记（```）
- 在顶层添加 schema 未定义的键
- 使用单引号、尾随逗号或未转义的换行

### Schema

```json
{
  "date": "YYYY-MM-DD",
  "overview": "2-3 句话概括今日最重要的主题与基调，要有信息密度，不要空话。",
  "top_news": [
    {
      "headline": "独立、清晰、能脱离上下文读懂的标题",
      "category": "宽泛分类名（见下方取值建议）",
      "key_points": ["要点 1：解释为什么重要", "要点 2：补充细节或影响"],
      "tags": ["#标签1", "#标签2"],
      "topic_path": "一级/二级/主题（2-3 层中文分类路径，如 'AI/LLM/微调'）",
      "original_link": "输入数据中的原始 URL，原样回填，不要改写",
      "source": "输入数据中的 source 字段，原样回填"
    }
  ]
}
```

### 字段约束

| 字段 | 必填 | 说明 |
|------|------|------|
| `date` | ✅ | YYYY-MM-DD 格式；使用今日日期 |
| `overview` | ✅ | 2-3 句；概括主题而非罗列条目；避免"今天有很多新闻"这类废话 |
| `top_news` | ✅ | **至少 8 条**（高质量文章不足 8 篇时，输出全部高质量文章） |
| `headline` | ✅ | 独立可读，不依赖 overview 上下文 |
| `category` | ✅ | 宽泛分类，建议取值：`AI` / `Mobile` / `Software` / `Cybersecurity` / `Big Tech` / `Hardware` / `DevTools` / `Open Source` / `Science` / `Business` / `Society` |
| `key_points` | ✅ | 1-3 条；每条解释"是什么 + 为什么重要/对谁有影响"，不要只复述标题 |
| `tags` | ✅ | 1-3 个；以 `#` 开头；中英文均可，保持简洁（如 `#Rust`、`#供应链安全`） |
| `topic_path` | ✅ | 2-3 层中文路径，用 `/` 分隔；用于构建主题树，需保持层级一致（如同级条目都用"AI/LLM/xxx"） |
| `original_link` | ✅ | **必须**从输入 article 的 `link` 字段原样复制，不要臆造或拼接 |
| `source` | ✅ | **必须**从输入 article 的 `source` 字段原样复制 |
