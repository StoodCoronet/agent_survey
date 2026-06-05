# Multi-Topic Survey 重构规范

## 目标

将当前单 topic（AI Agent）的 survey pipeline 重构为支持多个 survey topic 的通用系统。用户可在不同 topic 间切换，每个 topic 拥有独立的 keywords、prompt、taxonomy、search query、deepdive 字段，共享 pipeline 代码和 venues 配置。

## 核心决策

| 维度 | 决定 |
|------|------|
| 架构模式 | 单系统多 topic：共享 pipeline，per-topic 配置覆盖 |
| 数据隔离 | 共享 SQLite（paper 级数据去重），per-topic 独立分类结果 + output 子目录 |
| 配置组织 | `config.yaml` 全局 + `topics/<name>.yaml` 按 topic 覆盖 |
| CLI 命令 | 保持 `survey_agent`，支持 `--topic` 参数 + `topic use` 设置活跃 topic |
| TUI | 顶部 topic 标签页，可随时切换；支持 TUI 内创建新 topic |
| LLM Prompt | 完整自定义 prompt，写在 topic yaml 中 |
| 搜索召回 | per-topic 自定义 query 列表 |
| Deepdive | per-topic 自定义提取字段 |
| 向后兼容 | 必须，现有 agent survey 数据完整保留 |

## 配置结构

### config.yaml（全局，改动最小化）

```yaml
years: { start: 2023, end: 2026 }
venues: { ... }        # 不变
network: { ... }       # 不变
paths: { ... }         # 不变
llm:                   # 模型选择保留，具体参数可由 topic 覆盖
  defaults:
    classify_model: deepseek-chat
    deepdive_model: deepseek-reasoner
    classify_temperature: 0.0
    deepdive_temperature: 0.0
docs:
  server_port: 48000
active_topic: gui-agent  # 当前活跃 topic
```

### topics/<name>.yaml（per-topic 完整配置）

```yaml
name: "GUI Agent Survey"
description: "Computer-use / GUI agent papers from SE/Security/AI venues"

# ------ prefilter keywords ------
keywords:
  include_rules:
    - match_any: ["GUI agent", "computer use", "web agent", ...]
    - match_all: [["LLM agent", "agentic"], ["testing", "fuzzing", ...]]

# ------ search recall queries ------
search_queries:
  - "GUI agent"
  - "computer use agent"
  - "web navigation agent"

# ------ classify prompts (full custom) ------
classify:
  system_prompt: |
    You are a meticulous research assistant...
  user_prompt_template: |
    Paper: {title} / {venue} ({year}) / {abstract}
    Label: relevance (core/related/adjacent/irrelevant), domain, method, tldr
  relevance_levels: ["core", "related", "adjacent", "irrelevant"]
  domain_labels:
    - "GUI Agent"
    - "Web Agent"
    - "Computer-Use Agent"
    - "SE Agent"
    - "Security Agent"
    - "Agent Safety & Privacy"
    - "General LLM Agent"
  method_labels:
    - "Benchmark/Dataset"
    - "Framework/System"
    - ...

# ------ taxonomy trees ------
taxonomy:
  trees:
    application-domain: { ... }
    technical-approach: { ... }
    research-goal: { ... }
  cross_cutting_tags: ["performance", "testing", ...]

# ------ deepdive extraction fields ------
deepdive:
  system_prompt: |
    You are a careful research assistant...
  user_prompt_template: |
    Extract: {fields} from paper text...
  fields:
    - name: problem
      description: "What problem does this paper address?"
      type: text
    - name: approach
      description: "Core method / system design"
      type: text
    - name: evaluation
      description: "How is it evaluated?"
      type: text
    # ... user-defined
```

## DB Schema 重构

### 设计原则
- `papers` 表存储论文本体（title/abstract/venue/year），与 topic 无关
- `paper_topics` 表存储 paper ↔ topic 关联 + per-topic 分类结果
- `topic_deepdive` 表存储 per-topic 的结构化提取（字段可变，用 JSON）

### 新 Schema

```sql
-- 论文本体（topic 无关）
CREATE TABLE papers (
  paper_id TEXT PRIMARY KEY,
  dblp_key TEXT UNIQUE,
  arxiv_id TEXT,
  doi TEXT,
  title TEXT NOT NULL,
  abstract TEXT,
  venue TEXT,
  venue_area TEXT,
  venue_type TEXT,
  year INTEGER,
  authors_json TEXT,
  url TEXT,
  pdf_url TEXT,
  pdf_path TEXT,
  code_url TEXT,
  prefilter_hit TEXT,        -- JSON: {topic_name: [matched_rules]}
  stage_status_json TEXT,    -- JSON: {topic_name: {stage: status}}
  created_at TEXT,
  updated_at TEXT
);

-- paper ↔ topic 关联 + 分类结果
CREATE TABLE paper_topics (
  paper_id TEXT NOT NULL,
  topic_name TEXT NOT NULL,
  relevance TEXT,
  domain_primary TEXT,
  domain_secondary_json TEXT,
  method_tags_json TEXT,
  tldr TEXT,
  rationale TEXT,
  dedup_keep BOOLEAN DEFAULT 0,
  taxonomy_json TEXT,        -- per-topic taxonomy classification
  topics_json TEXT,          -- per-topic topic labels (stage6)
  short_title TEXT,          -- per-topic abbreviated title
  summary_en TEXT,           -- per-topic bilingual summary
  summary_zh TEXT,
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (paper_id, topic_name)
);

-- per-topic deepdive 提取结果
CREATE TABLE topic_deepdive (
  paper_id TEXT NOT NULL,
  topic_name TEXT NOT NULL,
  fields_json TEXT,          -- 结构化提取字段（per-topic 格式不同）
  body_snapshot TEXT,        -- 提取时用的 PDF 文本摘要
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (paper_id, topic_name)
);

-- LLM 调用缓存（保留不变）
CREATE TABLE llm_calls (...);

-- topic 元信息
CREATE TABLE topics (
  topic_name TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  description TEXT,
  config_hash TEXT,          -- yaml 文件 hash，检测配置变更
  is_active BOOLEAN DEFAULT 0,
  created_at TEXT,
  updated_at TEXT
);

-- harvest 检查点（保留不变）
CREATE TABLE harvest_runs (...);

-- taxonomy 描述（加 topic_name）
CREATE TABLE taxonomy_descriptions (
  topic_name TEXT NOT NULL,
  tree_name TEXT NOT NULL,
  path TEXT NOT NULL,
  desc_en TEXT,
  desc_zh TEXT,
  paper_count INTEGER DEFAULT 0,
  metadata_json TEXT,
  status TEXT,
  last_error TEXT,
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (topic_name, tree_name, path)
);
```

### 迁移策略
1. 创建新表 `paper_topics`, `topic_deepdive`, `topics`
2. 迁移现有数据：所有已分类 paper 的 `relevance/domain/method/taxonomy/deepdive` 拷贝到 `paper_topics` + `topic_deepdive`，`topic_name = 'gui-agent'`
3. 旧的 `papers` 表删除已迁移的 per-topic 列
4. 创建 `gui-agent` topic 记录

## CLI 命令变更

```bash
# 全局操作（不变）
survey_agent harvest
survey_agent stats

# topic 管理
survey_agent topic list                          # 列出所有 topic
survey_agent topic new <name>                    # 交互式创建新 topic
survey_agent topic use <name>                    # 设置活跃 topic
survey_agent topic show [name]                   # 显示 topic 配置

# topic 感知的 pipeline（从活跃 topic 或 --topic 读取）
survey_agent enrich --topic gui-agent
survey_agent prefilter --topic gui-agent
survey_agent classify --topic gui-agent --workers 5
survey_agent search-recall --topic gui-agent
survey_agent fulltext --topic gui-agent
survey_agent deepdive --topic gui-agent
survey_agent taxonomy --topic gui-agent
survey_agent short-titles --topic gui-agent
survey_agent category-desc --topic gui-agent
survey_agent summary --topic gui-agent
survey_agent report --topic gui-agent
survey_agent generate-docs                    # 生成所有 topic 的 docs

# topic 参数优先级：--topic flag > active_topic > 报错
```

## TUI 重构

### 布局变更
```
┌──────────────────────────────────────────────┐
│  🤖 Agent Survey Dashboard                   │
│  ┌──────────┬──────────┬──────────┬───────┐  │
│  │ gui-agent│ fuzzing  │ + New   │       │  │  ← topic 标签页
│  └──────────┴──────────┴──────────┴───────┘  │
│ ┌─ Pipeline ──────┐ ┌─ 概况 ───────────────┐ │
│ │ ✅ harvest      │ │ 总:12,345  摘:8,200   │ │
│ │ ✅ enrich       │ │ C:234 R:567 A:1,200  │ │
│ │ > prefilter     │ │                       │ │
│ │   classify      │ └──────────────────────┘ │
│ └─────────────────┘                          │
│ ↑↓选择 Enter执行 q退出 | 活跃topic: gui-agent │
└──────────────────────────────────────────────┘
```

### 关键交互
- **Tab 切换**: ← → 键在 topic 标签间切换，切换后 pipeline 状态刷新
- **+ New**: 最后一个标签是 "+ New"，回车进入 topic 创建流程
- **Topic 创建流程**:
  1. 输入 topic name (kebab-case)
  2. 输入 display name
  3. 输入描述
  4. 选择 "从现有 topic 复制配置" 或 "从空白创建"
  5. 如果是复制，列出已有 topic 供选择
  6. 创建 `topics/<name>.yaml` 骨架
  7. 提示用 Claude Code interview 模式优化 prompt

## 项目文件结构

```
survey_agent/
├── config.yaml                    # 全局配置
├── topics/                        # per-topic 配置目录
│   ├── gui-agent.yaml             # 现有 AI agent survey
│   └── <new-topic>.yaml           # 未来 topic
├── output/
│   ├── db/papers.sqlite
│   ├── gui-agent/                 # per-topic output
│   │   ├── json/
│   │   ├── markdown/
│   │   ├── obsidian/
│   │   ├── pdfs/
│   │   └── stats/
│   ├── <new-topic>/
│   └── logs/
├── docs/                          # 所有 topic 混合生成
│   ├── data.json
│   ├── index.html
│   └── ...
├── src/agent_survey/
│   ├── cli.py                     # + topic 子命令群 + --topic 参数
│   ├── tui.py                     # + topic 标签页 + 创建流程
│   ├── core/
│   │   ├── config.py              # + TopicConfig model, topic loading
│   │   ├── db.py                  # + paper_topics, topic_deepdive, topics 表
│   │   └── console.py
│   ├── services/
│   │   ├── llm.py                 # 移除硬编码 prompt → 从 topic config 读取
│   │   ├── taxonomy.py            # 移除硬编码 taxonomy → 从 topic config 读取
│   │   ├── topic_manager.py       # 新: topic 生命周期管理
│   │   └── ...
│   ├── stages/
│   │   ├── s00_harvest.py         # 几乎不变
│   │   ├── s00b_search_recall.py  # 接受 topic 参数 → per-topic queries
│   │   ├── s01_enrich.py          # 几乎不变
│   │   ├── s02_prefilter.py       # 接受 topic 参数 → per-topic keywords
│   │   ├── s03_classify.py        # 接受 topic 参数 → per-topic prompts
│   │   ├── s04_fulltext.py        # 几乎不变（但 scope 变 topic-aware）
│   │   ├── s05_deepdive.py        # 接受 topic 参数 → per-topic fields
│   │   ├── s06_topics.py          # 接受 topic 参数
│   │   ├── s06b_subtopic_dedup.py # 接受 topic 参数
│   │   ├── s07_taxonomy.py        # 接受 topic 参数 → per-topic trees
│   │   ├── s08_citation.py        # 几乎不变
│   │   ├── s09_short_titles.py    # 接受 topic 参数
│   │   ├── s10_category_desc.py   # 接受 topic 参数
│   │   └── s11_summary.py         # 接受 topic 参数
│   ├── analysis/
│   └── report/                    # per-topic output 渲染
```

## 实现阶段

### Phase 1: 基础架构（2-3 天）
1. 创建 `multi-topic` 分支
2. 实现 `topics/<name>.yaml` 加载 + `TopicConfig` Pydantic model
3. DB migration: 创建新表，迁移现有数据，清理旧列
4. `survey_agent topic list|use|show|new` 命令

### Phase 2: Pipeline 适配（2-3 天）
5. 改造 `prefilter`: 从 topic config 读取 keywords
6. 改造 `classify`: 从 topic config 读取 prompts + labels
7. 改造 `search-recall`: 从 topic config 读取 queries
8. 改造 `deepdive`: 从 topic config 读取 extraction fields
9. 改造 `taxonomy`: 从 topic config 读取 trees
10. 改造 `category-desc`, `short-titles`, `summary`
11. 所有 CLI 命令加 `--topic` 参数，支持 fallback 到活跃 topic

### Phase 3: TUI 重构（1-2 天）
12. TUI 顶部 topic 标签页 + 切换逻辑
13. TUI 内 "+ New" 创建 topic 流程
14. Per-topic pipeline 状态刷新

### Phase 4: 验证 & 文档（1 天）
15. 用 `gui-agent` topic 完整跑一遍，确认与重构前结果一致
16. 创建第二个测试 topic 验证切换流程
17. 更新 CLAUDE.md、README.md
