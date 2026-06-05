# Topic 输出隔离实施计划

## 现状

`Config.abs_topic_dir(topic_name, kind)` 已定义但**未被任何代码使用**。当前所有输出仍落在扁平目录：

```
output/
  json/           # llm-agent 的 JSON 也在里面
  markdown/       # llm-agent 的 Markdown 也在里面
  obsidian/       # llm-agent 的 Obsidian vault 也在里面
  pdfs/           # 所有 topic 的 PDF 混放
  stats/          # 所有 topic 的 stats 混放
  logs/           # 所有 topic 的日志混放
```

## 目标

让 `llm-context-management` topic 的 survey 成果完全隔离到 `output/llm-context-management/` 下，不污染 `llm-agent` 的数据。

## 实施步骤

### Step 1: 修改 PathsCfg（配置层）

`PathsCfg` 当前是单 topic 的扁平路径设计。改为：
- 保留 `db`、`llm_cache` 为全局共享（数据库和 LLM 缓存是 topic 无关的）
- `json_dir`、`markdown`、`obsidian`、`pdfs` 不再在 `PathsCfg` 中硬编码，改由 `abs_topic_dir()` 动态生成

### Step 2: 修改 report 模块（输出层）

| 文件 | 当前路径 | 目标路径 |
|------|---------|---------|
| `report/markdown.py` | `cfg.abs_dir("json")` | `cfg.abs_topic_dir(topic_name, "json")` |
| `report/markdown.py` | `cfg.abs_dir("markdown")` | `cfg.abs_topic_dir(topic_name, "markdown")` |
| `report/obsidian.py` | `cfg.abs_dir("obsidian")` | `cfg.abs_topic_dir(topic_name, "obsidian")` |

### Step 3: 修改 stage 模块

| Stage | 当前路径 | 目标路径 |
|-------|---------|---------|
| `s04_fulltext` | `cfg.abs_dir("pdfs")` | `cfg.abs_topic_dir(topic_name, "pdfs")` |
| `analysis/stats.py` | `output/stats/` | `output/<topic>/stats/` 或保持全局 |

> **stats 的处理**：`write_stage_stats` 是全局的（记录每次运行），但 topic 维度的 stats 应该可以按 topic 分组查看。建议保持 `output/stats/` 为全局，但文件名包含 topic（如 `stats/classify_llm-context-management_20260601.json`）。

### Step 4: 迁移现有数据

`llm-agent` 的现有输出需要迁移到 `output/llm-agent/` 下，避免用户找不到旧数据。

```bash
mkdir -p output/llm-agent
mv output/json output/llm-agent/json
mv output/markdown output/llm-agent/markdown
mv output/obsidian output/llm-agent/obsidian
mv output/pdfs output/llm-agent/pdfs
```

> **注意**：`pdfs/` 是全局共享的（同一篇论文的 PDF 不需要每个 topic 都下载一份）。建议 PDF 保持全局 `output/pdfs/`，各 topic 通过 symlink 或路径引用访问。

### Step 5: 验证

1. 切换 active_topic 为 `llm-context-management`
2. 跑 `agent-survey stats`，确认输出到 `output/llm-context-management/`
3. 切换回 `llm-agent`，确认旧数据仍在 `output/llm-agent/`

## 决策

- **DB**: 全局共享（papers, llm_calls, harvest_runs）
- **PDFs**: 全局共享（同一篇论文只下载一次）
- **JSON/Markdown/Obsidian/Stats**: per-topic 隔离
- **Logs**: 全局共享，但文件名包含 topic
