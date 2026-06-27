# Prompt Template Systems — 参考项目与文档

> 为 Argos 自定义模板系统（custom prompt templates）寻找设计参考。

---

## 一、直接相关项目（最值得参考）

### 1. PromptL（Latitude）

- **GitHub**: https://github.com/latitude-dev/promptl
- **Python binding**: https://github.com/latitude-dev/promptl-py
- **Stars**: ~100 | **License**: MIT
- **定位**: 专为 LLM 设计的模板语言
- **核心思路**:
  - 在 Markdown 头部加入 YAML frontmatter 定义 `model`、`temperature`
  - 支持 `<step>`、`<system>`、`<user>` 标签区分消息角色
  - 支持条件控制流、循环、变量插值
  - 编译为标准的 messages array，兼容任何 provider
  - 通过 WASM 实现跨语言调用
- **对 Argos 的参考价值**:
  - YAML frontmatter 方案很适合 `app/prompts/*.md` 的增强 —— 可以在模板文件头部声明 `temperature`、`max_tokens` 等参数
  - 其标签语法（`<step>`、`<system>`）可以用来替代 Argos 当前在 Python 代码中拼接 `schema_suffix` + `lang_directive` 的方式

### 2. Character.AI Prompt Poet

- **GitHub**: https://github.com/character-ai/prompt-poet
- **Stars**: ~1,100 | **License**: MIT
- **Python**: `pip install prompt-poet`
- **核心思路**:
  - YAML + Jinja2 混合模板
  - 每个 prompt 片段有 `name`、`role`、`content`、`truncation_priority`
  - 支持列表插值和条件渲染
  - 两步处理：Jinja2 渲染 → YAML 加载 → Python 数据结构
- **对 Argos 的参考价值**:
  - `truncation_priority` 机制 —— 当上下文超长时按优先级截断，Argos 也可以引入
  - YAML 结构化的多片段组织方式，适合复杂 prompt 的组合

### 3. project-thoth

- **GitHub**: https://github.com/acertainKnight/project-thoth
- **Stars**: ~10 | **License**: Apache 2.0
- **定位**: 本地优先的 AI 研究助手
- **核心思路**:
  - 所有 prompt 都是 Jinja2 模板文件，放在 `templates/` 目录
  - 用户可以直接阅读和编辑模板
  - 设计哲学："No hidden prompt engineering"
- **对 Argos 的参考价值**:
  - 和 Argos 当前 `app/prompts/*.md` 方案最为接近
  - 通过其 README 和源码可以学到如何组织模板目录结构、如何做 prompt 可配置化

### 4. jinja-prompt-manager

- **GitHub**: https://github.com/maylad31/jinja-prompt-manager
- **Stars**: ~6 | **License**: MIT
- **核心思路**:
  - Jinja2 模板 + SQLite 做 prompt 版本管理
  - 每个 prompt 有版本号、评分、生产环境选择
  - 沙箱化 Jinja2 环境（`ImmutableSandboxedEnvironment`）
- **对 Argos 的参考价值**:
  - DB schema 设计（版本、评分、active 标记）
  - 沙箱安全 —— 防范模板中的恶意代码执行

---

## 二、Prompt 管理平台（参考功能设计）

### 5. Langfuse

- **GitHub**: https://github.com/langfuse/langfuse
- **Stars**: 26,000+ | **License**: MIT
- **定位**: 开源 LLM 可观测性 + Prompt 管理平台
- **核心功能**:
  - Prompt 版本管理（版本号、标签、回滚）
  - Prompt-as-Configuration：prompt 更新无需重新部署
  - 内置 Playground 测试 prompt
  - A/B 测试、环境管理（dev/staging/production）
  - 客户端 SDK 缓存，零延迟
- **参考价值**:
  - 版本管理 + 标签机制是 Argos 可选的扩展方向
  - 其数据模型（[Prompt Management Data Model](https://langfuse.com/docs/prompt-management/data-model)）值得阅读
  - 缺点是太重（需要 ClickHouse + Redis + MinIO），不适合 Argos

### 6. Agenta

- **GitHub**: https://github.com/agenta-ai/agenta
- **Stars**: ~3,900 | **License**: MIT
- **定位**: 开源 LLMOps 平台（Prompt 管理 + 评估 + 可观测性）
- **核心功能**:
  - Prompt Playground（对比 50+ 模型输出）
  - 版本控制 + 配置管理
  - 评估框架（LLM-as-judge）
- **参考价值**:
  - Playground 交互式对比功能的设计思路
  - 评估体系可以作为 Argos 模板质量回溯的参考

### 7. PromptLayer

- **网站**: https://promptlayer.com
- **定位**: 生产级 Prompt 监控和版本管理
- **核心功能**:
  - API 代理层自动记录所有 LLM 调用
  - 版本追踪 + 一键回滚
  - A/B 测试 + 成本分析
- **参考价值**:
  - API 代理模式（非侵入式监控）
  - 成本追踪和预算告警功能

---

## 三、架构模式与最佳实践

### 8. Template Syntax Basics for LLM Prompts（Latitude Blog）

- **URL**: https://latitude.so/blog/template-syntax-basics-for-llm-prompts
- **内容**: 模板语法的核心概念：变量插值、控制流、模块化、错误处理
- **适合谁读**: 设计 Argos 模板变量系统之前

### 9. Jinja2 Prompting Guide（Medium）

- **URL**: https://medium.com/@alecgg27895/jinja2-prompting-a-guide-on-using-jinja2-templates-for-prompt-management-in-genai-applications-e36e5c1243cf
- **内容**: 如何使用 Jinja2 做 prompt 管理的最佳实践
- **代码示例**: https://github.com/alexgg278/jinja2-llm-prompting
- **适合谁读**: 理解 Jinja2 在 prompt 场景下的用法（条件、循环、继承）

### 10. How to Organize Prompt Templates for LLMs（Latitude Blog）

- **URL**: https://latitude.so/blog/organize-prompt-templates-llms
- **内容**: 文件夹结构、命名规范、版本控制、元数据标签、协作工作流
- **适合谁读**: 设计模板目录结构和命名规范时参考

### 11. Beyond Prompt Engineering: Systematic Prompting

- **URL**: https://inductivee.com/blog/prompt-engineering-production-systems
- **核心观点**: "每个生产级 prompt 都应该是一个 Jinja2 模板，带有显式的变量声明"
- **适合谁读**: 理解为什么 Jinja2 是 prompt 管理的最佳基础

---

## 四、LLM Chat Templates 合集

### 12. LLM Chat Templates

- **GitHub**: https://github.com/jndiogo/LLM-chat-templates
- **Stars**: ~46
- **内容**: 大量主流 LLM 的 Jinja2 chat template 示例
- **对 Argos 的价值**: 学习不同模型对 prompt 格式的差异要求

### 13. LLM Prompt Library（abilzerian）

- **GitHub**: https://github.com/abilzerian/LLM-Prompt-Library
- **Stars**: ~1,600
- **内容**: 实验性 Jinja2 模板合集，覆盖 OpenAI、Anthropic、DeepSeek 等
- **对 Argos 的价值**: 模板编写风格参考

---

## 五、与 Argos 当前实现的对比总结

| 方面 | Argos 当前 | PromptL | Prompt Poet | project-thoth | Langfuse |
|------|-----------|---------|-------------|---------------|----------|
| 模板格式 | 纯 Markdown | YAML frontmatter + Markdown | YAML + Jinja2 | Jinja2 .j2 | 纯文本 + 变量 |
| 变量注入 | 支持（未使用） | `{{ var }}` | `{{ var }}` | `{{ var }}` | `{{ var }}` |
| 角色区分 | 代码拼接 | `<system>` 标签 | `role:` 字段 | 代码拼接 | 代码拼接 |
| 参数声明 | 代码中硬编码 | YAML frontmatter | YAML 结构 | 代码中 | 配置元数据 |
| 版本管理 | 无 | Git | Git | Git | 内置版本系统 |
| UI 编辑 | 无 | Latitude 平台 | 无 | 无 | Langfuse Console |
| 存储 | .md 文件 | 文件 | 文件 | 文件 | 数据库 |
| 安全沙箱 | 无 | 无 | 无 | 无 | N/A（DB 存储） |

## 六、推荐阅读顺序

1. **先读** [Jinja2 Prompting Guide](https://medium.com/@alecgg27895/jinja2-prompting-a-guide-on-using-jinja2-templates-for-prompt-management-in-genai-applications-e36e5c1243cf) — 理解 Jinja2 在 prompt 领域的基础用法
2. **再读** [Template Syntax Basics](https://latitude.so/blog/template-syntax-basics-for-llm-prompts) — 理解模板语法设计的要素
3. **看源码** [project-thoth](https://github.com/acertainKnight/project-thoth) 的 `templates/` 目录 — 最接近 Argos 的实践
4. **看文档** [Langfuse Prompt Management Data Model](https://langfuse.com/docs/prompt-management/data-model) — 理解生产级版本管理的数据模型
5. **评估** [PromptL](https://github.com/latitude-dev/promptl) 的 YAML frontmatter 方案是否适合引入 Argos
