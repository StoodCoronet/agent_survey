# Domain Expert：一个 LLM 维护的学术领域调研系统

**目标会议：** ICSE/ASE 2027 Tool Demo Track

---

## 摘要（Abstract）

文献调研是学术研究的基石，但持续追踪、深入理解一个研究领域极为
耗时。研究者必须不断跟踪新工作、对比方法、识别矛盾、综合发现——
这是一个**持续的领域探究过程**，至今仍以手工艺为主且不可复现。
我们提出 **Domain Expert**，一个摄入学术论文全文、抽取带段落级
溯源的结构化事实、并维护自生长知识库的系统。该知识库支持跨论文
推理、矛盾检测和证据可追溯的自然语言查询——定位为一个**持久的
研究助手**，而非一次性的报告生成器。我们的核心洞察是：**系统
本身就是 Weng (2026) 意义上的启发式系统（Heuristic System）**——
LLM coding agent 通过持续反馈（读取失败日志、吸收用户纠错、周期
压缩知识图谱）来维护和演化抽取 schema、事实校验规则和知识压缩
启发式。整个过程不涉及模型重训练；所有学习通过代码+数据的协同
演化完成。我们构建在一个成熟的多 topic 文献 pipeline 之上，该
pipeline 已爬取 20+ SE/Security/AI 会议期刊的 70,000+ 篇论文，
其 enrich 策略本身就是通过我们将要形式化的启发式学习过程发现的。
评估计划包括 3 个研究领域的自动化 benchmark 和 10-15 名研究者
的用户研究，对比对象为 GPT-4+搜索、Semantic Scholar 和静态
调研报告。

---

## 1. 引言（Introduction）

学术研究正以前所未有的速度增长，使得研究者越来越难以维持对任何
领域的深度、及时理解。软件工程、安全和 AI 领域的顶级会议每年各
发表数千篇论文。研究者必须持续探究新工作、对比方法、识别矛盾、
综合发现——这是一个**持续的领域调研过程**，至今仍以手工艺为主
且不可复现。

现有工具只覆盖部分环节：Semantic Scholar 提供引用图和 TLDR 摘要；
Elicit 和 Consensus 提供基于 RAG 的学术搜索；PaperQA2 支持单个
PDF 的问答。但它们没有一个维护**持久、生长、可验证的知识库**——
能够随时间累积结构化事实、并支持带有证据溯源的跨论文推理。

我们提出 **Domain Expert**，将领域调研从一次性生成任务转变为
**活的启发式系统**。系统摄入 PDF 全文、抽取结构化事实、以自然
语言回答查询并追溯到原文段落。它维护每个 topic 独立的知识库，
随每篇新论文生长，并定期自我压缩以防止知识腐化。抽取 schema、
事实校验规则和压缩启发式本身由 LLM coding agent 通过持续反馈维
护——这是 **启发式学习（Heuristic Learning）** 范式（Weng 2026）
在学术知识管理领域的首次应用。

**贡献：**

1. 将启发式学习（Weng 2026）应用于学术知识管理——HL 从未在知识工作
   领域被验证过的概念框架
2. 一套可运行的端到端系统：摄入 PDF 全文、抽取带段落级证据溯源的
   结构化事实、支持自然语言跨论文推理查询
3. 具备 HL 两个核心操作的自生长知识库：**Absorb**（新论文 → 检测
   新发现/矛盾）和 **Compress**（周期 claim 聚类和证据合并）
4. 启发式学习的实践案例研究：发现 venue-adaptive enrichment 策略
   的过程——通过代码演化（而非模型训练）实现 20 个 venue 的 95%+
   摘要覆盖率

---

## 2. 背景与动机（Background & Motivation）

### 2.1 启发式学习（Heuristic Learning）

翁家翌（2026）近期提出了**启发式学习（Heuristic Learning, HL）**
作为一种新的学习范式。核心论点是：coding agent（写代码并维护代码
的 LLM）可以产出一个不依赖梯度下降就能持续改进的学习系统。Agent
读取失败日志、修改代码、添加测试、审视回放，使**启发式系统
（Heuristic System, HS）**——一套通过代码演化不断变强的程序化策略
系统——持续生长。

健康的 HS 需要两个操作：

1. **吸收反馈（Absorb feedback）：** 将新失败、新日志、新数据写入系统
2. **压缩历史（Compress history）：** 将积累的补丁折叠成更简单、
   更可维护的表示——"只增长不压缩的 HS，最后一定会变成屎山代码"

Weng 在 Atari 游戏（Breakout 达理论满分 864）和 MuJoCo 机器人
（Ant 达深度 RL 量级的 6000+）上验证了 HL——全部使用纯 Python 代码，
零神经网络训练。

### 2.2 学术文献工具的缺失

HL 在游戏和控制任务上得到了验证。我们认为它同样适用于——且可能
影响更大——**学术知识管理**。"环境"变成了 PDF 语料和用户查询；
"反馈"变成了缺失事实、用户纠错和检测到的矛盾；"策略"变成了抽取
pipeline 和知识图谱维护规则。

| 维度 | Weng 的 Atari/MuJoCo HS | 我们的 Domain Expert HS |
|------|----------------------|---------------------|
| 环境 | 游戏引擎、物理模拟器 | PDF 语料、用户查询 |
| 反馈 | Reward 信号、视频回放 | 缺失事实、用户纠错、矛盾检测 |
| 策略 | 启发式策略代码 | 抽取 pipeline + 事实校验规则 |
| 状态 | 游戏变量 | 知识图谱：claims、证据跨度、关系 |
| 记忆 | trials.jsonl, summary.csv | 向量库、事实库、版本化 claim 历史 |
| 回归测试 | 固定 seed 重放 | 查询一致性检查 |

---

## 3. 方法（Approach）

### 3.1 系统总览

```
┌─────────────────────────────────────────────────────────────────┐
│                     Domain Expert System                         │
│                                                                  │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│   │   Ingest     │───→│   Extract    │───→│   Query      │←──User
│   │   (Absorb)   │    │   Facts      │    │   Interface  │      │
│   └──────────────┘    └──────────────┘    └──────────────┘      │
│         ↑                                                  │     │
│    New papers                                       NL queries  │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Knowledge Base (per-topic, grows over time)              │  │
│   │                                                           │  │
│   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │  │
│   │  │ Full-text   │  │ Structured  │  │ Claim       │       │  │
│   │  │ Chunks      │  │ Facts       │  │ Graph       │       │  │
│   │  │ (vector)    │  │ (SQL+JSON)  │  │ (relations) │       │  │
│   │  └─────────────┘  └─────────────┘  └─────────────┘       │  │
│   │                        │                                   │  │
│   │                  ┌─────────────┐                           │  │
│   │                  │ Versioned   │                           │  │
│   │                  │ History     │                           │  │
│   │                  │ (superseded │                           │  │
│   │                  │  preserved) │                           │  │
│   │                  └─────────────┘                           │  │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Maintenance Loop (Heuristic Learning)                     │  │
│   │                                                           │  │
│   │  Absorb ──→ New paper → extract → compare →               │  │
│   │              NEW / UPDATE / CONFIRM / CONFLICT             │  │
│   │                                                           │  │
│   │  Compress ──→ Periodically: cluster claims,               │  │
│   │                merge evidence, archive superseded          │  │
│   │                                                           │  │
│   │  Verify ──→ Regression-test: re-ask old questions,        │  │
│   │               check answer consistency                     │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 第一层：知识摄入（Absorb 反馈）

**PDF Processing Pipeline：**

```
PDF file
  ↓  marker-pdf / pdfplumber (section-aware parsing)
Section-annotated text blocks
  ↓  semantic chunking (recursive split + section boundary merge)
Chunks (500-1000 tokens each)
  ↓  embedding (text-embedding-3-small / DeepSeek)
Vector store (LanceDB, per-topic collection)
  ↓  LLM extraction (DeepSeek, structured JSON schema)
Structured facts + evidence spans
```

**结构化抽取 Schema（per-topic 可配置）：**

```yaml
fact_types:
  method_claim:
    fields: [method_name, task, dataset, metric, score, evidence_span]
    description: "Method X achieves score Y on dataset Z"
  comparison:
    fields: [method_a, method_b, benchmark, result, direction, evidence_span]
    description: "Method A outperforms Method B by N points"
  limitation:
    fields: [limitation_text, category, evidence_span]
  contradiction:
    fields: [claim_a, claim_b, paper_a, paper_b, nature, evidence_span]
```

### 3.3 第二层：知识综合（查询引擎）

```
User query: "Does Method X outperform Method Y on ImageNet?"
  ↓  embedding → vector search
Top-k chunks across papers (k=20, diversity-reranked)
  ↓  structured fact lookup (SQL: method=X AND method=Y AND dataset=ImageNet)
Hybrid context: chunks + structured facts + claim graph neighbors
  ↓  LLM multi-document synthesis (DeepSeek-Reasoner / GPT-4)
Answer with inline citations + evidence list
```

**支持的查询类型：**

| 查询类型 | 示例 | 机制 |
|---------|------|------|
| 事实查询 | "BERT 用了什么数据集？" | 向量 + 结构化事实检索 |
| 对比分析 | "BERT vs RoBERTa 在 GLUE 上？" | 双路检索 + 结构化对比 |
| 趋势发现 | "ImageNet top-1 2023-2025 如何变化？" | 指标 claims 按时间聚合 |
| 矛盾检测 | "有没有论文反对 dropout 是必需的？" | Claim 相似度 + 否定检测 |
| 证据强度 | "Finding X 有几篇独立验证？" | Claim 图入度 |
| 空白分析 | "任务 Y 上还有哪些架构没试过？" | Taxonomy 覆盖度 - 已有 claims |

### 3.4 第三层：自生长知识（维护循环）

**Absorb — triggered by each new paper：**

```
New paper ingested
  ↓  extract structured facts
  ↓  compare each fact against existing KB
  ↓  classify:
      ├─ NEW: previously unseen method/dataset/claim → add
      ├─ UPDATE: improves SOTA on existing benchmark → add, mark old as superseded
      ├─ CONFIRM: replicates existing finding → add, increment evidence count
      └─ CONFLICT: contradicts existing claim → add, flag for user attention
```

**Compress — triggered periodically or by user：**

```
Trigger: KB facts exceed threshold, or user requests synthesis
  ↓  cluster semantically similar claims across papers
  ↓  merge redundant evidence chains into single consensus entry
  ↓  identify stale/contradicted claims → mark as superseded, preserve in history
  ↓  generate consensus snapshot: current best-evidence claims per topic
```

### 3.5 案例研究：通过 HL 发现 Enrichment 策略

在形式化 Domain Expert 架构之前，我们已经实践了启发式学习来解决
一个具体的子问题：**跨异构学术 venue 的摘要补全。**

```
Phase 1: 探测环境（Probe）
  → 测试 31 个 venue+year 组合，每组合 10 篇论文
  → 优先级：S2 API → arXiv API → OpenReview API → venue fetcher

Phase 2: 读取失败日志（Absorb 反馈）
  → USS (USENIX Security): S2 仅覆盖 3-10%
  → TOSEM 2023: S2 仅覆盖 50%
  → CHI, FSE, UIST, ISSTA: S2 覆盖 90-100%

Phase 3: Agent 修改代码（Code update）
  → 编写 strategies/usenix.py: fetch_usenix_abstract() 通过 httpx
  → 编写 strategies/crossref.py: fetch_crossref_abstract() 通过 DOI API
  → 重构 sources.py: 按 venue 优化的 source 选择表

Phase 4: 验证改善（Verify）
  → TOSEM 2023: 50% → 99% 覆盖率（107/108 篇）
  → USS 2025: 60% S2 + 40% venue fallback = 100%

Phase 5: 压缩历史（Compress）
  → 31 个探测结果压缩为 _VENUE_SOURCES 字典:
    Tier 1 (S2 主导): CHI, FSE, ISSTA, UIST, NAACL, NeurIPS, EMNLP
    Tier 2 (S2 + OpenReview): ICML, ACL, CCS, COLM, AAAI
    Tier 3 (Venue fetcher 为主): USS
  → 记录在 devdocs/venue-enrich-strategies.md 作为回归 artifact
```

这个微观案例展示了 Domain Expert 的全部五个阶段：probe → absorb →
modify → verify → compress。同样的反馈循环现在扩展到全文知识抽取。

---

## 4. 评估方案（Evaluation Plan）

> **注意：** 本节为评估大纲。自动化 benchmark 和用户研究尚未执行。
> RQ 设计参考了 TradeSweep (Lee et al., ICSE 2025) [2] 的评估结构。

### 4.1 研究问题（Research Questions）

TradeSweep [2] 的 RQ 结构——分别从 **自动化正确性**、**用户效率**
和 **可用性/信任** 三个维度评估——直接适用于我们的系统。我们在
此基础上增加了 **纵向生长** 和 **证据溯源信任** 两个维度，对应
HL 框架的核心主张。

| RQ | 类型 | 问题 | 对应 TradeSweep [2] |
|----|------|------|---------------------|
| **RQ1** | 自动化 | Domain Expert 能否准确召回和抽取研究领域的关键论文与 SOTA claims？ | ~ RQ1 (code correctness) |
| **RQ2** | 自动化 | 与 ground truth 相比，结构化事实抽取的 precision/recall 如何？ | ~ RQ1 (execution success) |
| **RQ3** | 用户研究 | Domain Expert 是否比现有工具（GPT-4 + search, Semantic Scholar）更快、更省力地完成文献调研任务？ | ~ RQ2 (task time, error rate) |
| **RQ4** | 用户研究 | 用户是否更信任 Domain Expert 的答案（因其可追溯到原文段落）？系统的可用性（SUS）和认知负荷（NASA-TLX）如何？ | ~ RQ3 (Likert satisfaction, SUS) |
| **RQ5** | 纵向 | 知识库是否随论文摄入持续改善（验证 HL 假设）？新论文是否能被正确分类为 NEW/UPDATE/CONFLICT？ | TradeSweep 未涉及 |

### 4.2 自动化评估（对应 RQ1, RQ2）

**数据集：** 从已爬取 venue 中选择 3 个研究领域，各构建 ground truth：
- Area A: GUI Agents (CHI, UIST)
- Area B: LLM Code Generation (ICSE, FSE)
- Area C: Federated Learning Security (USS, CCS, NDSS)

**Ground truth 构建（每个领域）：**
- 关键论文列表：领域专家指定 30-50 篇
- SOTA claims：20-30 条事实三元组 (method, dataset, metric, score)
- 已知矛盾：5-10 对冲突 claim pairs
- 方法 taxonomy：3-4 层 hierarchy

**RQ1 指标（召回与覆盖）：**

| 指标 | 定义 | 目标 |
|------|------|------|
| Paper recall@k | 专家标记论文在 KB 中的召回率 (k=10, 20, 50) | ≥ 80% |
| Claim extraction recall | Ground truth claims 被成功抽取的比例 | ≥ 70% |
| Taxonomy coverage | 每类 taxonomy 下至少 3 篇论文的比例 | ≥ 90% |

**RQ2 指标（准确度）：**

| 指标 | 定义 | 目标 |
|------|------|------|
| Claim precision | 抽取的事实中经人工验证正确的比例 | ≥ 85% |
| Evidence accuracy | 事实对应的 evidence span（原文段落）是否正确 | ≥ 80% |
| Answer quality | LLM-as-judge (GPT-4 blind)，Likert 1-5 | ≥ 3.5 |
| Contradiction recall | Ground truth 矛盾中被系统检测到的比例 | ≥ 60% |
| Hallucination rate | 综合答案中无法追溯到 KB 的 claims 比例 | ≤ 10% |

### 4.3 用户研究（对应 RQ3, RQ4）

**参与者：** 12-20 名研究者（PhD 学生、博后），SE/AI/ML 领域
（TradeSweep 为 32 人；我们目标 12-20 作为 tool demo 可行）

**设计：** Within-subjects, counterbalanced order

**任务（每条件 5 题，共 30 min）：**
1. Factual lookup: "Task X 上最佳 reported accuracy 是多少？"
2. Comparison: "比较 Method A 和 B——哪个更好，差距多大？"
3. Dataset survey: "Task Y 常用哪些数据集，各自规模如何？"
4. Limitation analysis: "Method Z 有哪些已知局限？"
5. Contradiction check: "有没有论文对 claim W 持相反结论？"

**条件（3 个）：**
| Condition | 工具 | 说明 |
|-----------|------|------|
| **Baseline 1** | Google Scholar + ChatGPT (web search) | 当前研究者常用方式 |
| **Baseline 2** | Semantic Scholar + 手动整理 | 学术搜索引擎 + 人工笔记 |
| **Treatment** | Domain Expert | 我们的系统 |

**RQ3 指标（效率）：**

| 指标 | 测量方式 |
|------|---------|
| Task completion time | 每个任务的完成时间 |
| Answer correctness | 盲审专家评分 (1-5)，参考 TradeSweep [2] |
| Source traceability | 答案中可追溯到原文的 claims 比例 |

**RQ4 指标（信任与可用性）：**

| 指标 | 测量方式 | 参考 |
|------|---------|------|
| System Usability Scale (SUS) | 标准 10-item 量表 | TradeSweep [2] |
| NASA-TLX | 认知负荷 6 维度量表 | TradeSweep [2] |
| Trust in answer | Likert 1-5: "我对这个答案的正确性有信心" | 我们新增 |
| Evidence utility | Likert 1-5: "能够追溯到原文段落对我有帮助" | 我们新增 |
| "Would you use this in your own research?" | 是/否 + free-text 理由 | TradeSweep [2] |

### 4.4 纵向试点（对应 RQ5）

部署 1 个活跃 topic 运行 3 个月：

| 追踪指标 | 说明 |
|---------|------|
| Papers ingested | 累计摄入论文数 |
| KB facts count | 知识库中结构化事实总数 |
| Claim graph density | 每篇论文的平均跨论文关系数 |
| Update accuracy | 新论文被正确分类为 NEW/UPDATE/CONFLICT 的比例 |
| Answer quality over time | 相同查询在不同 KB 大小下的答案质量变化 |
| KB staleness | 论文发表到 KB 更新的中位时间差 |
| Compression events | 触发次数 + 压缩前后 KB 大小对比 |

**HL 假设验证：** 绘制 answer quality vs KB age 散点图，假设呈正相关趋势。

### 4.5 定性分析（Qualitative Analysis）

参考 TradeSweep [2] 的 failure analysis 做法：

- **成功案例：** 选取 3-5 个典型成功查询，展示 evidence trace 和 synthesis 过程
- **失败模式分类：** 分析错误答案的根因（缺失论文、抽取错误、综合错误、矛盾漏检）
- **用户反馈分类：** 对 free-text 反馈做主题编码
- **Compress 前后对比：** 展示一次 compress 前后的 KB 变化

### 4.6 Evaluation 与 TradeSweep [2] 的结构性对比

| 维度 | TradeSweep [2] | Domain Expert |
|------|---------------|---------------|
| 自动化任务数 | 30 preprocessing tasks | 3 领域 × 20-30 claims = 60-90 验证点 |
| 用户研究人数 | 32 participants | 12-20 (tool demo 可接受) |
| 对比 baselines | 3 (GPT-4o, Data Wrangler, Code Interpreter) | 3 (GPT-4+search, S2+manual, static survey) |
| 测量维度 | Correctness, time, error rate, SUS, Likert | 以上全部 + source traceability + trust + longitudinal |
| 独有维度 | Code library growth | Evidence provenance, contradiction detection, HL growth |
| 纵向 | 未涉及（单次会话） | 3 个月试点（核心 novelty） |

---

## 5. 相关工作（Related Work）

### 5.1 启发式学习

Weng (2026) 提出启发式学习作为一种新范式：coding agent 通过代码
演化（而非梯度下降）维护持续生长的启发式系统。在 Atari Breakout
（864，理论满分）、MuJoCo Ant（6000+，深度 RL 量级）和 Atari57
（中位数 HNS 超越 PPO）上的结果证明了该范式在游戏和控制任务上的
可行性。我们的工作首次将 HL 应用于**知识工作**——一个反馈模态更
丰富（用户纠错、矛盾检测、过时标记）、对压缩要求更强（防止知识
图谱腐化）的领域。

### 5.2 LLM 辅助文献综述

**RAG 工具**（Elicit、Consensus、PaperQA2）使用检索增强生成在学术
论文上回答问题，但运行在单会话、无状态范式下——无持久知识累积。

**系统综述工具**（ASReview、Colandr、Rayyan）使用主动学习加速
论文筛选，但止于筛选阶段——无抽取、综合或跨论文推理。

**LLM Survey 生成**（我们自己的 survey_agent 及类似系统）从爬取的
论文中生成结构化 survey 报告，但将报告视为最终产品——知识在生成后
被丢弃。

### 5.3 SE 会议上的 LLM 工具论文

TradeSweep（Lee et al., ICSE 2025 Tool Demo）证明了一个工程良好、
具有双轨评估（自动化 + 用户研究）的 LLM 工具可以发表在顶级 SE
会议上。他们的系统为电子表格预处理检索代码模板；我们的系统为
文献综合检索结构化事实。架构模式——RAG + LLM 生成 + 人类反馈
循环——是共享的，但我们的系统增加了持久性、自生长和 HL 概念框架。

### 5.4 知识库与专家系统

经典专家系统（MYCIN、DENDRAL）将领域知识编码为手工规则——有效但
维护成本极高。现代知识库（Wikidata、DBPedia）覆盖面广但浅——事实
三元组，无证据溯源或矛盾处理。我们的系统结合了专家系统的深度和
LLM 的广度，通过 HL 将维护成本控制在可接受范围内。

---

## 6. 结论与未来工作（Conclusion & Future Work）

我们提出了 **Domain Expert**，一个 LLM 维护的学术文献启发式系统，
摄入 PDF 全文、抽取带证据溯源的结构化事实、通过自然语言查询支持
跨论文推理。核心贡献是将文献管理重新定义为 **启发式学习** 问题：
系统通过代码+数据的协同演化（而非模型重训练）持续改进，以显式的
Absorb 和 Compress 操作维持知识库健康。

我们构建在已爬取 20+ 会议期刊的成熟 survey_agent pipeline 之上，
并以 venue-adaptive enrichment 策略的发现过程作为 HL 的微观验证。
Enrichment 的故事——探测 31 个组合、吸收失败模式、修改代码、验证
改善、压缩为策略表——就是我们现在扩展到全文知识抽取的同一个学习
循环的具体实例。

**未来工作：**
- 完成评估（自动化 benchmark + 用户研究）
- 实现压缩 pipeline（claim 聚类、证据合并）
- 探索跨 topic 知识迁移（一个研究领域学到的知识辅助另一个领域）
- 研究如何使 HL 维护循环更加自主，减少人工介入

---

## 参考文献（References）

[1] Weng, J. (2026). *Learning Beyond Gradients.*
    https://trinkle23897.github.io/learning-beyond-gradients/

[2] Lee, C.-T., Neeser, A., Xu, S., Katyan, J., Cross, P., Pathakota, S.,
    Norman, M., Simeone, J., Chandrasekaran, J., & Ramakrishnan, N. (2025).
    Can an LLM Find Its Way around a Spreadsheet? In *Proceedings of the
    IEEE/ACM 47th International Conference on Software Engineering (ICSE '25)*,
    pp. 294–306. IEEE Press. DOI: 10.1109/ICSE55347.2025.00101
