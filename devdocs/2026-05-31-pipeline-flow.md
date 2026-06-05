# Survey Agent Pipeline 数据流与阶段设计

> 文档日期: 2026/05/31
> 对应分支: `multi-topic`
> 用途: 帮助理解每个 pipeline 阶段存在的业务原因、数据量变化和可优化空间

---

## 一、整体流程

```mermaid
flowchart TD
    A[harvest<br/>~70k papers<br/>DBLP 元数据] --> B[enrich<br/>S2/arXiv/OpenReview<br/>补 abstract]
    B --> C[enrich-web<br/>Playwright fallback<br/>补剩余 abstract]
    C --> D[prefilter<br/>关键词正则<br/>标记 prefilter_hit]

    D --> E{classify (s03)<br/>LLM 判断 relevance<br/>输入: title + abstract}
    E -->|core| F[core<br/>~1-2k]
    E -->|related| G[related<br/>~2-3k]
    E -->|adjacent| H[adjacent<br/>~3-5k]
    E -->|irrelevant| I[irrelevant<br/>直接丢弃]

    F --> M[taxonomy (s07)<br/>动态 N-tree 分类<br/>输出 taxonomy_json + topics_json]
    G --> M
    H --> M

    M --> R[dedup (s06b)<br/>子主题发现 + 去重]

    R --> J[fulltext<br/>下载 arXiv PDF]
    J --> L[deepdive (s05)<br/>DeepSeek-Pro<br/>读 PDF 正文<br/>结构化提取]

    L --> N[short-titles<br/>缩写标题]
    N --> O[category-desc<br/>分类描述]
    O --> P[summary<br/>双语摘要]
    P --> Q[report<br/>Obsidian vault]

    style I fill:#fee,stroke:#c00
    style K fill:#eee,stroke:#999
    style L fill:#efe,stroke:#0a0
    style M fill:#eef,stroke:#00c
```

**颜色说明**

| 颜色 | 含义 |
|------|------|
| 绿色 (deepdive) | **唯一读 PDF 正文** 的步骤 |
| 红色 (irrelevant) | 被丢弃，不进入后续流程 |
| 蓝色 (taxonomy) | 动态 N-tree 分类，支持增量扩展新维度 |
| 灰色 (adjacent) | 可选是否进入 deepdive |

---

## 二、各阶段业务描述与存在必要性

### Stage 0: harvest（数据入口）

**做什么**
- 从 DBLP API 按 (venue, year) 组合批量爬取论文元数据：title, authors, venue, year, url(doi/openreview/arXiv)
- 支持会议、期刊、TOC XML 三种抓取模式

**为什么必须存在**
- 这是整个 pipeline 的唯一数据来源。没有 harvest，后续所有阶段都没有输入。
- DBLP 是计算机领域最完整的论文索引，覆盖 SE/Security/AI 主要 venue。

**数据量**: ~70k papers（全局共享，所有 topic 共用同一份）

**是否 per-topic**: 否

---

### Stage 1: enrich（补全 abstract）

**做什么**
- 对 `abstract IS NULL` 的论文，并发查询三个来源：arXiv API → Semantic Scholar API → OpenReview API
- 按标题模糊匹配，取第一个有 abstract 的结果

**为什么必须存在**
- DBLP 不提供 abstract。没有 abstract，prefilter 和 classify 都无法工作（它们依赖 title+abstract 做判断）。
- 三个来源互补：arXiv 覆盖预印本，S2 覆盖正式出版物，OpenReview 覆盖 ICLR/ICML 等会议。

**数据量**: 63k+ 缺 abstract → 预计补 30k-35k（harvest 阶段新增 OpenReview/Publisher 爬取后）

**是否 per-topic**: 否（全局操作，abstract 是 paper 级属性）

**成本**: ~$5-10（主要消耗 S2 API 调用）

---

### Stage 1b: enrich-web（兜底补 abstract）

**做什么**
- 对 enrich 仍然失败的论文，用 Playwright 打开 arXiv 搜索页，爬取 abstract
- arXiv crawl-delay = 3s，单线程/低并发

**为什么必须存在**
- S2/OpenReview 也有覆盖不到的论文（特别是非英语 title、拼写差异大的情况）。
- Playwright 模拟真实浏览器，能绕过部分反爬虫。

**数据量**: 通常 1k-3k 篇需要 web 兜底

**是否 per-topic**: 否

**成本**: 时间成本高（3s/篇），但 API 费用为 0

---

### Stage 2: prefilter（低成本粗筛）

**做什么**
- 对所有 70k 篇论文的 title+abstract 跑正则匹配
- 逻辑: `agent_core` OR (`agent_generic` AND (`se_context` OR `sec_context`))
- 输出: `papers.prefilter_hit` = `{topic_name: {agent_core: [...], se_context: [...]}}`

**为什么必须存在（不与 classify 合并的原因）**
| 方案 | 成本 | 7w 篇总费用 | 风险 |
|------|------|------------|------|
| **当前**: prefilter(0) + classify($0.001/篇) | $0 + $15 | **~$15** | prefilter 有假阴性（关键词没命中但实际相关） |
| **合并**: 直接 classify 全部 70k | $0.001 × 70k | **~$70-100** | 无假阴性，但成本高 5-7 倍 |

**结论**: prefilter 是**成本防火墙**。它的唯一目的就是减少 classify 的输入量。如果预算充足且追求覆盖率，可以考虑用 embedding 粗筛替代正则，但 retain 一个"低成本前置筛子"的结构不变。

**数据量**: 70k → ~10k-15k 命中（per-topic 独立计算）

**是否 per-topic**: 是（每个 topic 有自己的 keywords，独立存储命中结果）

**成本**: 0（本地正则，无 API 调用）

---

### Stage 3: classify（精筛 + 标签）

**做什么**
- 对 prefilter 命中的论文，用 DeepSeek-Flash 判断 relevance: core / related / adjacent / irrelevant
- 同时输出: domain_primary（领域）、method_tags（方法标签）、tldr（一句话总结）

**为什么必须存在**
- prefilter 只能回答"这篇论文可能相关"，无法回答"有多相关"和"属于什么领域"。
- classify 的 `relevance` 直接决定论文**进不进最终 report**（通常只收 core + related）。
- `domain_primary` 和 `method_tags` 给 report 提供结构化标签，用于分组和过滤。

**数据量**: ~10k（prefilter 命中）→ core(~1-2k) + related(~2-3k) + adjacent(~3-5k)，irrelevant 丢弃

**是否 per-topic**: 是（每个 topic 有自己的 prompt 和 relevance 标准）

**成本**: ~$15-20（batch 处理，10 篇/调用）

---

### Stage 4: fulltext（下载 PDF）

**做什么**
- 对 core/related 的论文，下载 arXiv PDF 到本地 `output/<topic>/pdfs/`

**为什么必须存在**
- deepdive 需要读 PDF 正文提取结构化信息。没有 PDF，deepdive 无法工作。

**数据量**: core + related = ~3-5k 篇

**是否 per-topic**: 否（PDF 文件全局共享，但不同 topic 可能下载不同子集）

**成本**: 0（带宽 + 磁盘）

---

### Stage 5: deepdive（读 PDF 正文）

**做什么**
- 用 DeepSeek-Pro (reasoner) 读 PDF 前 40 页，提取结构化字段
- 每个 topic 有自己的提取模板（如: problem, method, limitation, code_url 等）

**为什么必须存在**
- 这是整个 pipeline **唯一真正读 PDF 正文** 的步骤。
- title+abstract 无法提供方法细节、实验结果、局限性等深度信息。
- deepdive 的输出是 report 中"论文详情页"的核心内容来源。

**数据量**: ~3-5k 篇（只处理 core/related）

**是否 per-topic**: 是（每个 topic 有不同的提取字段需求）

**成本**: ~$50-80（Pro 模型贵，但只在高质量论文上用）

---

### Stage 6: taxonomy（统一多维分类 — 已吸收原 classify-topics）

**做什么**
- 对 title+abstract，在 topic 配置的动态多维 tree 上分类（如 application-domain、technical-approach、research-goal，或任意自定义维度）
- 同时输出：
  - `taxonomy_json`：树形路径（如 `research-goal/attack-redteam/jailbreak-attack`）
  - `topics_json`：平面标签（通过 `flat_labels` 映射从 tree paths 推导）
- 支持增量发现新叶子/新维度：LLM 可提议 `new_leaves`（如 `"vr-agent/immersive-interface"`），代码自动将其加入对应 tree 并持久化到 `output/<topic>/taxonomy_extensions.json`
- tree 维度完全由 topic YAML 的 `taxonomy.trees` 定义，不同 topic 可定义完全不同的分类维度

**为什么合并 s06 + s07 以 s07 为准**
- 两者输入完全相同（title+abstract），目的相似（主题分类），只是数据结构不同。
- 3-tree（或 N-tree）结构给 report 提供**树形导航**，这是平面列表无法替代的。
- 通过 `flat_labels` 映射，tree 路径可无损转换为平面 topic IDs（替代了原 s06 的 seed topics）。
- `new_leaves` 机制吸收了 s06 的增量发现能力，且更进一步：可以自动创建全新 tree 维度。

**数据量**: core + related + adjacent = ~3-5k 篇

**是否 per-topic**: 是（每个 topic 有自己的 trees + flat_labels）

**成本**: ~$10-15（Flash 模型批量处理）

**持久化**
- 基础 tree 定义在 `topics/<name>.yaml`
- LLM 自动发现的新 leaves/branches/trees 写入 `output/<topic>/taxonomy_extensions.json`，下次加载时自动合并
- 待审核的 leaf 提案写入 `output/<topic>/pending_leaves.json`

---

### Stage 8-11: 后处理（纯文本生成）

| 阶段 | 输出 | 存在原因 |
|------|------|---------|
| short-titles | `paper_topics.short_title` | 原始标题太长，report 需要缩写版做列表展示 |
| category-desc | `taxonomy_descriptions` 表 | 给每个 taxonomy 节点生成双语描述，report 导航页用 |
| summary | `paper_topics.summary_en/zh` | 论文详情页需要 3-4 句摘要，比原始 abstract 更易读 |
| report | Obsidian vault + JSON + Markdown | 最终交付物 |

**成本**: 很低（Flash 模型，批量处理）

---

## 三、阶段合并讨论结论

### ✅ 保持独立：prefilter + classify

原因: 成本差异太大。prefilter 是 0 成本的防火墙，删掉它会让 classify 的输入量 ×7，费用从 $15 涨到 $100+。

**优化方向**: 把 prefilter 的命中规则（命中了哪些关键词）作为上下文写入 classify 的 prompt，减少 LLM 的重复理解，而不是合并成一个阶段。

### ✅ 已合并：classify-topics + taxonomy（以 taxonomy 为准）

原因: 两者输入相同、目的相似（主题分类），只是数据结构不同。

**合并后实现**:
1. 原 seed topics 映射为 `taxonomy.flat_labels`，tree 路径自动推导平面 topic IDs
2. taxonomy prompt 动态生成 JSON schema，支持任意 N 个 tree 维度
3. LLM 可提议 `new_leaves`（完整路径如 `"tree/branch/leaf"`），代码自动将其加入对应 tree；若 tree 不存在则新建 tree
4. 新发现的 leaves/branches/trees 持久化到 `output/<topic>/taxonomy_extensions.json`，下次加载时自动合并进 topic config
5. 删掉 s06 代码和 `TaxonomyManager`，CLI / TUI 中移除 `classify-topics` 步骤

---

## 四、成本总览（按当前流程，per-topic）

| 阶段 | 模型 | 估算费用 | 时间 |
|------|------|---------|------|
| enrich | S2/arXiv/OpenReview API | ~$5-10 | 30-60 min |
| enrich-web | Playwright | $0 | 1-3h |
| classify | DeepSeek-Flash | ~$15-20 | 30-60 min |
| deepdive | DeepSeek-Pro | ~$50-80 | 2-3h |
| taxonomy | DeepSeek-Flash | ~$10-15 | 20-30 min |
| 后处理 | DeepSeek-Flash | ~$5-10 | 10-20 min |
| **总计** | | **~$90-135** | **~5-7h** |

---

## 五、关键设计决策（架构层面）

1. **papers 表全局共享** — title/abstract/venue/year 不重复存储，70k 篇只存一份
2. **paper_topics 表 per-topic** — relevance/taxonomy/summary 独立，支持同一篇论文在不同 topic 下有不同的分类结果
3. **topic_deepdive 表 per-topic** — 结构化提取结果独立，不同 topic 关注不同字段
4. **stage_status_json 是 topic-scoped** — 支持不同 topic 跑到不同阶段，互不影响
5. **LLM 调用有缓存** — `llm_calls` 表按 input_hash 去重，重跑时自动跳过已完成的调用

---

## 六、当前待优化项

- [x] harvest 阶段加入 `--fetch-abstracts`（OpenReview API + Publisher 爬虫）
- [ ] ACM Digital Library 返回 403，无法通过 HTTP/Playwright headless 获取 abstract（留到 enrich 阶段通过 S2 补）
- [ ] ACL Anthology 无静态 abstract（需 enrich 阶段通过 S2 补）
- [x] s06 classify-topics 与 s07 taxonomy 合并（taxonomy 作为 canonical，支持动态 N-tree + flat_labels + new_leaves 自动扩展）
- [ ] **待讨论**: prefilter 命中结果是否应作为 classify prompt 的上下文输入
