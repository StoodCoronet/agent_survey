# Agent Survey Crawler & Analyzer — 项目规划

## 1. 目标

爬取 CCF-A 顶会 / 顶刊中 **AI Agent（侧重 computer-use agent / GUI agent）** 方向的论文，并聚焦 **软件工程** 与 **安全/隐私** 相关子主题，为后续 survey 做数据支撑。

## 2. 覆盖范围

### 2.1 Venues（会议 + 期刊）

| 领域 | Venues |
|---|---|
| 软工四大 | ICSE, FSE (ESEC/FSE), ASE, ISSTA |
| 软工期刊 | TOSEM, TSE |
| 安全四大 | S&P (Oakland), CCS, USENIX Security, NDSS |
| AI/ML | ICLR, NeurIPS, ICML, AAAI |
| NLP | ACL, EMNLP, NAACL, COLM |
| HCI | CHI, UIST |

### 2.2 时间范围

2023 至今（含 2026 当年已公布论文）。

### 2.3 主题聚焦

**主线**：AI Agent，尤其 Computer-Use Agent / GUI Agent / Web Agent / Mobile Agent。
**交叉方向**（加分项，但非必须）：
- 软件工程：测试 / 测试生成 / benchmark / 程序分析 / 代码生成 / debug / RPA
- 安全隐私：prompt injection / jailbreak / agent 安全 / 隐私泄露 / 攻击防御 / side channel

## 3. 数据源策略

| 目的 | 数据源 | 备注 |
|---|---|---|
| 会议论文列表 | DBLP `venue/year` JSON | 权威、无反爬；不提供 abstract |
| Abstract 补全 | Semantic Scholar Graph API | 免费；按 DOI / title 查询 |
| Preprint & PDF | arXiv API | 按 title 匹配；只有 arXiv 上的才下载全文 |
| 备用元数据 | OpenAlex（可选） | S2 查不到时兜底 |

> 不使用 Google Scholar（反爬严格）和 ACM/IEEE DL（需订阅）。

## 4. Pipeline 总览

```
                ┌─ [A] DBLP 全量拉 (venue, year) → title + metadata
                │                        │
                │                        ├─ enrich: S2 补 abstract / arxiv_id
                │                        │
                │                        └─ prefilter: keyword 正则粗筛
                │                                   (title + abstract)
                │
[Stage 0/1/2]  ─┤
                │
                └─ [B] 搜索支线: S2 / arXiv 用 "GUI agent" 等 query 搜
                                           │
                                           └─ 反向按 DBLP venue + year 过滤
                                                 (保证只留目标会议论文)

                ── 合并去重 → candidates 表 ──

[Stage 3] classify:    DeepSeek-V4-Flash(非思考) 读 title+abstract，判相关性 + 打标签
                              |                     仅 relevance != "irrelevant" 进入下一步
[Stage 4] fulltext:    arXiv 有 PDF 的下载 + 分章节文本抽取（pdfplumber）
                              |
[Stage 5] deepdive:    DeepSeek-V4-Pro(思考模式) 结构化抽取 problem/method/evaluation/
                              |                   dataset/code_url/limitation
                              |
[Stage 6] report:      生成 Obsidian 笔记 + 结构化 JSON + Markdown 综述 + 分类表
```

### 两条入口支线的分工

| 支线 | 驱动 | 强项 | 弱项 |
|---|---|---|---|
| A. DBLP 全量 | venue+year 硬性约束 | 权威、全量、不会漏会议论文 | DBLP 只有 title，要靠 S2 补 abstract |
| B. 搜索召回 | "GUI agent" / "computer use" 等 query | 捞回 keyword 没命中但语义相关的 | 需反向按 venue 过滤，S2 对小众长 query 排序不稳 |

两支线结果在 DB 中按 `paper_id`（首选 DBLP key，次选 DOI / arxiv_id / title-year 哈希）去重，`source_flags` 字段标注 `dblp / s2_search / arxiv_search`。

### 每阶段 checkpoint + 统计

每个子命令跑完：
1. 打印本次处理数 / 累计总数 / 分 venue 分布
2. 把统计结果写到 `output/stats/{stage}_{timestamp}.json`
3. DB 里在 `papers.stage_status_json` 记录每篇在每个阶段的处理状态

每一阶段**独立可重跑**、**有 LLM 缓存**：重复跑只处理 `stage_status_json` 里没标 done 的。
用户可以 prefilter 跑完先看统计（保留多少篇），再决定是否进 classify。

## 5. 相关性 / 分类体系

### 5.1 Stage 3 相关性档位（LLM 输出）

- `core`：主题就是 computer-use / GUI / Web / Mobile agent
- `related`：LLM agent 在软工或安全场景下的应用（如 agent for testing / agent security）
- `adjacent`：仅 LLM agent 通用方法或 tool use，未直接涉及 GUI/SE/Sec
- `irrelevant`：不相关

保留 `core` + `related` + `adjacent` 进入 Stage 4/5，`irrelevant` 仅存档备查。

### 5.2 二维分类（初版）

**维度 A — 场景 / 领域**
1. GUI Agent（desktop / mobile GUI 操作）
2. Web Agent（浏览器、网页任务）
3. Computer-Use Agent（整机操作、multi-app workflow）
4. SE Agent（agent for coding / testing / debugging / code review）
5. Security Agent（agent for pentest / vuln discovery / defense）
6. Agent Safety & Privacy（针对 agent 本身的攻击 / 防御 / 隐私）
7. General LLM Agent（框架、planning、tool-use 通用工作）

**维度 B — 研究方法 / 贡献类型**
1. Benchmark / Dataset
2. Framework / System
3. Empirical Study / Measurement
4. Attack
5. Defense / Mitigation
6. Evaluation / Analysis Method
7. Application（落地、case study）

每篇论文可能落多个 B 标签，A 取主标签 1 个 + 次标签若干。

后续可根据实际结果演化为层级 taxonomy。

## 6. 关键词（初版，写在 config.yaml 里可调）

```yaml
keywords:
  agent_core:
    - "GUI agent"
    - "computer use"
    - "computer-use agent"
    - "screen agent"
    - "web agent"
    - "mobile agent"
    - "autonomous agent"
    - "tool-use agent"
    - "multimodal agent"
    - "visual agent"
    - "browser agent"
    - "desktop agent"
    - "os agent"
  agent_generic:
    - "LLM agent"
    - "language agent"
    - "agentic"
    - "large language model agent"
  se_context:
    - "test generation"
    - "fuzzing"
    - "software testing"
    - "program repair"
    - "code generation"
    - "debugging"
    - "benchmark"
    - "regression test"
    - "GUI testing"
    - "Android testing"
    - "app testing"
  sec_context:
    - "prompt injection"
    - "jailbreak"
    - "adversarial"
    - "privacy leak"
    - "side channel"
    - "malware"
    - "vulnerability"
    - "penetration"
    - "red team"

prefilter_rule:
  # 粗筛：必须命中 agent_core 或 (agent_generic AND (se_context OR sec_context))
  include_if: "agent_core OR (agent_generic AND (se_context OR sec_context))"
```

## 7. 模型使用（DeepSeek V4）

| 阶段 | 模型 | 模式 | 典型输入/输出 | 成本量级 |
|---|---|---|---|---|
| Stage 3 classify | `deepseek-v4-flash` | 非思考 | ~500 tok in / ~150 tok out | 几分钱/千篇 |
| Stage 5 deepdive | `deepseek-v4-pro` | 思考模式 | ~6k tok in / ~800 tok out | 几元/百篇（2.5 折期内） |

- 客户端：OpenAI 格式兼容，Base URL `https://api.deepseek.com`。
- 所有调用结果按 `(paper_id, stage, model, prompt_version)` 缓存到 `cache/llm/*.json`，避免重复消费。
- JSON Output 开启，强制结构化返回。

## 8. 输出制品

```
output/
├── db/
│   └── papers.sqlite           # 单一事实源：papers, authors, venues, labels, llm_calls
├── json/
│   └── papers.json             # 完整导出，便于再处理
│   └── taxonomy.json           # A/B 维度下的分类树
├── markdown/
│   └── survey.md               # 人读综述（按 A 维度分章，带引用）
│   └── classification_table.md # 大表：title | venue | year | A | B | relevance | tldr
├── obsidian/                   # Obsidian vault 子目录
│   ├── README.md
│   ├── index.md                # MOC，链接到所有分类标签
│   ├── tags/                   # 每个 A 维度一个笔记
│   └── papers/
│       └── {year}-{venue}-{slug}.md   # 每篇一个笔记，YAML frontmatter + wikilinks
└── pdfs/                       # arXiv 下载的 PDF（.gitignore）
```

### Obsidian 笔记模板

```markdown
---
title: "..."
authors: [...]
venue: ICSE
year: 2025
doi: ...
arxiv: 2501.xxxxx
url: https://...
code: https://github.com/...
relevance: core
domain_primary: GUI Agent
domain_secondary: [SE Agent]
method_tags: [Benchmark, Framework]
tags: [agent/gui, se/testing]
---

# {title}

## TL;DR
(一句话)

## Problem
## Approach
## Evaluation
## Key Findings
## Limitations
## My Notes
```

## 9. 项目结构

```
agent_survey/
├── pyproject.toml              # uv 管理
├── .env                        # DEEPSEEK_API_KEY, S2_API_KEY(optional)
├── .env.example
├── config.yaml                 # venues, years, keywords, paths
├── README.md
├── PLAN.md                     # 本文件
├── src/agent_survey/
│   ├── __init__.py
│   ├── cli.py                  # 子命令：harvest / enrich / prefilter / classify / fulltext / deepdive / report
│   ├── config.py
│   ├── db.py                   # SQLite schema + CRUD
│   ├── sources/
│   │   ├── dblp.py
│   │   ├── semantic_scholar.py
│   │   ├── arxiv.py
│   │   └── openalex.py
│   ├── pipeline/
│   │   ├── harvest.py
│   │   ├── enrich.py
│   │   ├── prefilter.py
│   │   ├── classify.py
│   │   ├── fulltext.py
│   │   └── deepdive.py
│   ├── llm/
│   │   ├── client.py           # DeepSeek client (OpenAI SDK)
│   │   ├── prompts.py
│   │   └── cache.py
│   ├── pdf/
│   │   └── extract.py          # pdfplumber 分节抽取
│   └── report/
│       ├── obsidian.py
│       ├── markdown.py
│       └── taxonomy.py
├── scripts/
│   └── run_all.sh              # 跑完整 pipeline
└── cache/
    └── llm/                    # prompt-response 缓存
```

## 10. DB Schema（核心表）

```sql
CREATE TABLE papers (
  paper_id TEXT PRIMARY KEY,          -- dblp key 或 arxiv id
  dblp_key TEXT UNIQUE,
  arxiv_id TEXT,
  doi TEXT,
  title TEXT NOT NULL,
  abstract TEXT,
  venue TEXT,
  venue_type TEXT,                    -- conf / journal
  year INTEGER,
  authors_json TEXT,
  pdf_url TEXT,
  pdf_path TEXT,
  code_url TEXT,
  tldr TEXT,
  relevance TEXT,                     -- core/related/adjacent/irrelevant/null
  domain_primary TEXT,
  domain_secondary_json TEXT,
  method_tags_json TEXT,
  deepdive_json TEXT,                 -- problem/method/eval/... 结构化结果
  stage_status_json TEXT,             -- {harvest: done, enrich: done, ...}
  created_at DATETIME,
  updated_at DATETIME
);

CREATE TABLE llm_calls (
  call_id TEXT PRIMARY KEY,
  paper_id TEXT,
  stage TEXT,
  model TEXT,
  prompt_version TEXT,
  input_hash TEXT UNIQUE,             -- 缓存命中依据
  response_json TEXT,
  created_at DATETIME
);
```

## 11. 执行计划

```bash
# 一次性（conda env 里用 uv pip）
conda activate agent_survey
uv pip install -e .

# 逐阶段（均可重跑 + checkpoint；每阶段末尾打印统计）
agent-survey harvest           # DBLP 全量（按 venue+year）
agent-survey search-recall     # S2/arXiv 搜 "GUI agent" 等 query，反向按 venue 过滤
agent-survey enrich            # 补 abstract / arxiv / pdf_url
agent-survey prefilter         # 本地 keyword 粗筛 title+abstract
agent-survey stats             # 看当前 DB 分布，决定是否继续
agent-survey classify          # DeepSeek-Flash 分类（只跑 prefilter 命中的）
agent-survey fulltext          # 下载 + 抽取 arXiv PDF
agent-survey deepdive          # DeepSeek-Pro 结构化抽取
agent-survey report            # 生成 Obsidian / JSON / Markdown 产物
```

## 12. 非目标 / 暂不做

- 不做 Google Scholar / 订阅数据库爬取
- 不做引用网络分析（可后续扩展）
- 不做 OCR（扫描 PDF 跳过）
- 不做自动增量定时（手动重跑即可，seen-id 机制保证增量）

## 13. 待确认 / 后续演进

- Taxonomy 首轮跑完后，根据实际 tag 分布收敛成稳定层级结构
- 是否加入 CHI/UIST 的 LBW/alt.chi 短文（目前默认不加）
- 是否对非 arXiv 论文通过作者主页兜底下载（目前不做）
