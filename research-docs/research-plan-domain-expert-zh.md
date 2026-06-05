# 研究计划：从 Survey 生成器到领域专家系统

**最后更新：** 2026-06-03
**状态：** 脑暴 / 预提案

---

## 0. 概念框架：启发式学习

### 0.1 Heuristic Learning 的核心思想

翁家翌（OpenAI）在其 2026 年的文章《Learning Beyond Gradients》[1] 中
提出了 **Heuristic Learning（启发式学习，HL）** 范式：

> Coding agent（写代码的 LLM）不训练神经网络、不更新权重，只是
> 持续看失败、改代码、加测试、看回放，就能把一套程序系统越养越强。
> 更新对象从模型参数变成了软件结构；反馈由 coding agent 消化，
> 来自环境 reward、testcase、日志、视频、回放或人类反馈。

一个健康的 **Heuristic System（HS）** 需要两个操作维持：

1. **吸收反馈（Absorb feedback）：** 把新失败、新日志、新数据写回系统
2. **压缩历史（Compress history）：** 把一堆局部补丁折回更简单、更可维护的表示

> *"只增长不压缩的 HS，最后一定会变成屎山代码。"*

核心洞察：**Coding agent 改变的是 heuristic 的维护成本曲线。**
过去很多启发式策略不是没用，而是没人养得起；coding agent 让
这些规则、测试、日志、memory 和补丁不再是散落的工程材料，而
可以组成一个会持续更新的 Heuristic System。

### 0.2 我们已经在做 Heuristic Learning

在 enrich 策略的设计过程中，我们已经在实践 HL，只是没给它命名：

| HL 阶段 | 我们的 Enrich 故事 |
|---------|-------------------|
| **探测环境** | 测试 31 个 venue+year 组合，每个 10 篇论文 |
| **读取失败信息** | USS S2 覆盖率 ~3%，TOSEM 2023 ~50% |
| **吸收反馈** | 发现需要 Crossref 处理 DOI，需要 usenix.org 处理 USS |
| **Agent 修改代码** | 编写 `strategies/crossref.py`，重构 `sources.py` 按 venue 分流 |
| **验证改善** | TOSEM 2023：50% → 99% 覆盖率 |
| **压缩历史** | 31 个测试结果压缩为一个 `_VENUE_SOURCES` 策略表 |
| **固化知识** | `devdocs/venue-enrich-strategies.md` 成为回归测试 artifact |

系统通过**代码演化**而非模型训练学到了 20 个 venue 的 95%+ 摘要覆盖率。

### 0.3 HL × 学术知识工作

Weng 在游戏（Atari, MuJoCo）和机器人控制上验证了 HL。我们提出的
是：**将 HL 应用于一个根本不同的领域 — 学术知识管理与文献综合。**

| 维度 | Weng 的 Atari/MuJoCo | 我们的领域专家系统 |
|------|---------------------|-------------------|
| 环境 | 游戏引擎、物理模拟器 | PDF 全文、用户查询 |
| 反馈 | Reward 信号、视频回放 | 缺失事实、用户纠错、矛盾检测 |
| 策略 Policy | Python 启发式策略 | 抽取 pipeline + 知识图谱 |
| 状态 State | 游戏状态变量 | 结构化事实、证据跨度、claim 图谱 |
| 记忆 Memory | trials.jsonl, summary.csv | 向量库、事实库、版本化 claim 历史 |
| 回归测试 | 固定 seed 重放 | 查询答案一致性、事实校验 |
| 压缩历史 | 简化策略代码 | 聚类 claims、合并证据、标记过时 |

**这构成了我们的 novelty 论点：HL 从未被应用于知识工作领域。**

---

## 1. 动机

### 1.1 survey_agent 现状

```
venue × year → DBLP 爬虫 → abstract 补全 → prefilter →
LLM 分类 → taxonomy → deepdive 深度抽取 → PDF 下载 →
citation 引用图 → summary 摘要 → 静态报告
```

一个系统化文献 survey 生成器，支持多 topic 并行，拥有通过 HL 演进而来
的 venue-adaptive enrichment 策略。

### 1.2 缺失的部分

论文被当成数据库行处理。报告生成后，PDF 全文被丢弃。深度抽取虽能
提取几个结构化字段，但 PDF 中真正有价值的大量文本——方法细节、
实验设计、数据集对比、limitation 讨论、矛盾发现——从未被系统化
存储和利用。

### 1.3 愿景：活的知识体

```
静态 survey 生成器                    活的领域专家系统
       ↓                                     ↓
生成报告 → 丢弃 PDF              摄入 PDF → 永久存储全文
                                抽取事实 → 结构化知识
                                回答查询 → 追溯到原文段落
                                新论文入库 → 自动标记新发现/矛盾
                                周期压缩 → 防止知识腐化
```

变成一个 **活的 Heuristic System**，随每一篇新论文生长。

---

## 2. 相关工作和定位

### 2.1 参考论文 A：TradeSweep（ICSE 2025 Tool Demo）[2]

- **问题：** 非程序员无法高效完成电子表格数据预处理（缺失值、类型转换、
  编码等）
- **方法：** 自然语言请求 → embedding 检索相关代码模板 → LLM 生成 pandas 代码
  → 样本执行 → 自动纠错 → 用户反馈 → 应用到完整数据集 → 保存代码到库
- **评估：** 30 个预处理任务（自动化指标）+ 32 人用户研究（SUS、时间、错误率）
- **Baselines:** GPT-4o 直接生成、Data Wrangler、Code Interpreter
- **启示：** Tool paper 不需要算法 novelty。完整系统 + 扎实 evaluation +
  human-in-the-loop 定位即可中 ICSE

### 2.2 参考论文 B：Learning Beyond Gradients（Weng, 2026）[1]

- **核心论点：** Coding agent 能产生一种新的学习范式——启发式学习。
  不依赖梯度下降，而是通过"读失败 → 改代码 → 加测试 → 看回放"来
  让系统持续变强
- **实验结果：** 用 GPT-5.4 Codex，零神经网络训练：Atari Breakout
  达到理论满分 864，MuJoCo Ant 达到 6000+（深度 RL 量级），Atari57
  中位数 HNS 超越 PPO
- **理论贡献：** 将 Continual Learning 从"如何更新参数且不遗忘"重新定义
  为"如何维护一个持续吸收反馈的软件系统"。旧能力被固化为回归测试、
  replay、golden trace——显式、可读、可删、可重构
- **耦合复杂度：** 定义了 Agent 能维护多复杂的系统——取决于代码侧
  的模块化/测试/日志/状态可复现性，和 agent 侧的模型能力/上下文
  长度/memory/工具质量
- **启示：** 我们的领域专家系统就是一个 Heuristic System。这个
  视角给了我们一个**概念贡献**，而不只是"我们造了一个工具"

### 2.3 相关系统对比

| 系统 | 方法 | 不足 |
|------|------|------|
| Elicit / Consensus | 学术搜索 + RAG | 无持久知识库，无跨论文推理 |
| OpenAI Deep Research | LLM agent + web search | 黑盒，无来源透明 |
| PaperQA2 | PDF RAG agent | 单次查询，无自生长语料 |
| Semantic Scholar | 引用图 + TLDR | 无自定义抽取，无矛盾检测 |
| TradeSweep (ICSE 2025) | RAG + LLM 代码生成 | 不同领域；单会话；无持久知识 |
| **我们的 Domain Expert** | **HL 驱动的知识系统** | **首次将 HL 应用于文献管理** |

### 2.4 TradeSweep [2] 与我们的领域专家 —— 结构性对比

TradeSweep（ICSE 2025 Tool Demo）在投稿 venue、scope、贡献风格上
和我们最接近。通过对比两套系统，既能验证我们投稿的可行性，也
能突出我们的增量贡献。

**相似之处（为什么我们能投同一个 track）：**

| 维度 | TradeSweep [2] | 我们的领域专家 |
|------|---------------|---------------|
| **Track** | ICSE Tool Demo | ICSE/ASE Tool Demo（目标） |
| **问题** | 非程序员处理表格数据 | 研究者文献 overload |
| **核心技术** | RAG + LLM 代码生成 + 执行 | RAG + LLM 事实抽取 + 综合 |
| **Human-in-loop** | 用户确认样本结果，自然语言反馈 | 用户纠错事实，自然语言提问 |
| **生长的库** | 保存代码模板 + pipeline | 生长的知识库 + 事实图谱 |
| **反馈循环** | 执行报错 → LLM 修改代码 | 缺失/矛盾事实 → agent 更新 KB |
| **Novelty 风格** | 工程整合，非算法 | 工程整合 + 概念框架（HL） |
| **评估方式** | 30 任务自动化 + 32 人用户研究 | 计划：相似结构 + 增加纵向评估维度 |

**差异之处（我们的系统更深的地方）：**

| 维度 | TradeSweep [2] | 我们的领域专家 |
|------|---------------|---------------|
| **生命周期** | 单次会话 | 持久，随时间增长（月/年） |
| **生长的对象** | 代码库（人工维护） | 知识库（agent 维护） |
| **记忆机制** | 会话范围，每次重设 | 持久：向量库 + 事实库 + 版本历史 |
| **持续学习** | 无 — 每次独立 | 有 — KB 累积，旧知识归档 |
| **压缩机制** | 无 | Claim 聚类、证据合并（HL 核心操作） |
| **来源追溯** | 不关注 | 段落级证据追踪（对可信度至关重要） |
| **概念框架** | 普通 RAG + 代码生成 | 启发式学习（Weng 2026）— 新颖定位 |
| **领域范围** | 一个工具（表格） | 每个 topic 一个专家实例，多 topic 架构 |
| **前期工作规模** | 代码模板（几十个） | 20 个 venue，7 万+ 论文，3.6 万+ PDF，多 topic pipeline |

**这个对比的意义：**

TradeSweep 证明了 ICSE Tool Demo 需要：
1. 定义清晰的用户痛点
2. 可运行的端到端系统
3. 双轨评估（自动化 + 用户研究）
4. 明确的反馈闭环（执行 → 修改 → 验证）

我们的领域专家系统满足以上全部 — 并在此基础上多了：
5. 概念框架（启发式学习应用于知识工作）
6. 纵向维度（系统随时间持续变好）
7. 更强的证据溯源（段落级引用追踪）

与 TradeSweep 的结构性相似验证了我们的 venue 选择；差异之处
则确立了我们的 novelty — 我们不是在做"论文 RAG"，而是在构建
一个通过 LLM coding agent 维护的自生长 Heuristic System，遵循
Weng 提出的 HL 范式。

---

## 3. Heuristic Learning 如何映射到我们的系统

### 3.1 概念映射

```
Weng 的启发式学习                    我们的领域专家系统
─────────────────                    ─────────────────

Coding Agent（LLM 写代码）         →  LLM 编写/更新抽取 schema、
                                      事实模板、压缩规则

环境                                 →  PDF 语料 + 用户查询 +
                                       反馈回路

反馈（reward, test failure,        →  缺失事实、用户纠错、
 log, replay）                         矛盾检测、过时 claim 标记

策略（heuristic code, rules）      →  抽取 pipeline +
                                       事实校验 + 答案综合

状态（变量、检测器、缓存）           →  知识图谱状态：claims、
                                       证据跨度、关系、版本历史

记忆（trials.jsonl,                →  向量库（全文）+
 summary.csv, replay 视频）            事实库（结构化）+
                                       claim 图（关系）+
                                       版本日志

回归测试（固定 seed 重放验证分数）   →  查询一致性检验：
                                       相同问题检查答案是否退化

压缩历史（简化策略、删除死规则）     →  周期 claim 聚类 +
                                       证据合并 + 过时归档
```

### 3.2 反馈循环

```
                    ┌──────────────────────┐
                    │   领域专家 HS         │
                    └──────────┬───────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
    新论文入库            用户提问             用户纠错
          │                    │                    │
          ▼                    ▼                    ▼
    抽取结构化事实        检索证据             标记错误 claim
    与已有 KB 比较       跨文档综合            记录为失败案例
          │                    │                    │
          ▼                    ▼                    ▼
    NEW / UPDATE /        生成带引用的           Agent 更新
    CONFIRM / CONFLICT    答案                  抽取 schema
          │                    │                    │
          └────────────────────┼────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  周期压缩（Compress）  │
                    │  聚类相似 claims      │
                    │  合并冗余证据         │
                    │  归档过时结论         │
                    │  生成 consensus 快照  │
                    └──────────────────────┘
```

### 3.3 管理耦合复杂度

Weng 将**耦合复杂度**定义为 HS 能维护多复杂策略的根本约束——
一次更新必须同时照顾多少相互牵连的状态、规则、测试、反馈和历史。

我们对抗耦合复杂度的手段：

| 防御机制 | 实现方式 |
|---------|---------|
| **模块化** | 每个 topic 独立的知识库，互不干扰 |
| **Schema 边界** | 每个 topic 有结构化的抽取 schema |
| **版本化历史** | 旧 claims 归档而非删除 |
| **回归测试** | 查询答案一致性检查 |
| **显式记忆** | 向量库 + 事实库（weights 里不压缩任何知识） |
| **周期压缩** | Claim 聚类、证据合并（防知识腐化） |

---

## 4. 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│              领域专家系统（Heuristic System）                  │
│                                                               │
│  ┌───────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │ 摄入       │ → │ 抽取     │ → │ 查询     │ ← │ 用户     │ │
│  │ (Absorb)  │   │ 事实     │   │ 界面     │   │ 输入     │ │
│  └───────────┘   └──────────┘   └──────────┘   └──────────┘ │
│        ↑                                               │      │
│   新论文                                          自然语言     │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ 知识库（per-topic，随时间生长）                         │   │
│  │  ├─ 全文分块（按 section 切分，向量索引）               │   │
│  │  ├─ 结构化事实（方法/数据集/指标/分数）                 │   │
│  │  ├─ Claim 关系图（矛盾/验证/引用）                     │   │
│  │  └─ 版本化历史（过时 claims 保留，不丢失）              │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ 维护循环（HL 实现）                                     │   │
│  │  ├─ Absorb: 新论文 → 抽取 → 分类变化类型               │   │
│  │  ├─ Compress: 聚类 claims, 合并证据, 归档              │   │
│  │  └─ Verify: 回归测试旧查询答案                          │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 4.1 Layer 1: 吸收反馈（Ingestion）

```
PDF → section 感知解析 → 按 section 分块 → embedding → 向量库
  ↓
LLM 结构化抽取 → 事实 + 证据跨度（原文段落位置）
  ↓
与已有知识比对 → 分类：NEW / UPDATE / CONFIRM / CONFLICT
```

### 4.2 Layer 2: 查询与综合

支持的查询类型：

- **事实查询：** "Method X 用了什么数据集？"
- **对比分析：** "Method A vs Method B 在 benchmark W 上谁好？"
- **趋势发现：** "2023-2025 这个方向的 accuracy 怎么变的？"
- **矛盾检测：** "有没有论文对 Claim Y 有相反结论？"
- **证据强度：** "Finding Z 有几篇独立验证过？"
- **空白分析：** "这个方向还有什么没被尝试过？"

### 4.3 Layer 3: 压缩历史（Maintenance）

```
触发：KB 超过阈值 / 周期调度 / 用户请求
  → 聚类相似 claims
  → 合并冗余证据链
  → 标记过时/矛盾 claims
  → 生成 consensus 快照
  → 旧版本保留（归档，不删除）
```

---

## 5. 现有组件 vs 新组件

### 5.1 复用 survey_agent 的部分

| 组件 | 在新系统中的角色 |
|------|----------------|
| `s00_harvest` | 论文发现（共享论文池） |
| `s01_enrich` | Venue-adaptive 摘要补全（HL 演进而来的策略） |
| `s03_classify` | Per-topic 相关性过滤 |
| `s04_fulltext` | PDF 下载 → 成为摄入 feeder |
| `s07_taxonomy` | Method/domain 分类 schema |
| `s08_citation` | 证据关系图骨架 |
| Topics YAML | Per-topic 专家配置 |
| LLM 缓存 | 成本控制 |

### 5.2 需要新构建的部分

| 组件 | 预估工作量 | 描述 |
|------|-----------|------|
| PDF section 解析器 | 3-4 天 | Section 感知的文本提取 |
| 向量存储 | 1-2 天 | LanceDB/ChromaDB，per-topic 集合 |
| 分块 + embedding | 1 天 | 语义分块，API 调 embedding |
| 事实抽取器 | 5-7 天 | 结构化抽取 + 证据跨度 |
| 多文档 RAG | 3-5 天 | 检索 → 重排 → 综合 |
| 矛盾检测器 | 5-7 天 | Claim 相似度 + 否定检测 |
| 增量更新器 | 3-4 天 | 新论文 → diff → 分类变化类型 |
| 查询界面 | 3-5 天 | TUI 聊天 + 可选 Web UI |
| 压缩 pipeline | 3-5 天 | Claim 聚类，证据合并 |
| 评估框架 | 7-10 天 | Ground truth + 指标 + 用户研究 |

**总预估工作量：35-50 天（一人全职）**

---

## 6. 评估方案

### 6.1 自动化评估

从已爬取的 venue 中选择 3 个 research area，手动构建 ground truth：
- 关键论文列表（30-50 篇）
- SOTA claims（每 area 20-30 个）
- 已知矛盾（每 area 5-10 个）
- 方法 taxonomy（3-4 层）

**指标：**

| 指标 | 衡量什么 |
|------|---------|
| Paper recall@k | 专家标记的关键论文找回率 |
| Claim precision | 抽取的事实中正确百分比 |
| Evidence accuracy | 事实对应的原文段落是否正确 |
| Contradiction recall | 已知矛盾被检测到的比例 |
| Answer quality | LLM-as-judge，Likert 1-5 |
| Update accuracy | 新论文分类正确率（NEW/UPDATE/CONFLICT） |

### 6.2 用户研究

- 10-15 名研究者（博士生、博后）
- 组内设计，交叉平衡：Google Scholar+ChatGPT vs 领域专家系统
- 测量内容：时间、正确率、来源可追溯性、SUS、NASA-TLX

### 6.3 Baselines

- ChatGPT-4 + web search
- Semantic Scholar + 手动检索
- Elicit / Consensus
- survey_agent 静态报告（我们自己现有的系统）

### 6.4 纵向评估

部署一个活跃 topic 运行 3 个月：
- 追踪：论文摄入量、用户查询量、答案评分、KB 增长
- 验证 HL 假设：系统是否**随时间变得越来越好**？

---

## 7. Novelty 论述

1. **首次将 Heuristic Learning 应用于知识工作**——Weng 的 HL 实验
   全部在游戏/机器人领域；我们证明 HL 同样适用于学术知识管理
2. **自生长知识库 + 可验证的证据溯源**——每个 claim 可追溯到原文
   段落；旧知识归档保留，不丢失
3. **完整实现 HL 的两个核心操作**——Absorb（新论文 → 检测变化
   类型）和 Compress（周期 claim 综合）
4. **通过架构设计管理耦合复杂度**——模块化 per-topic 隔离、结构化
   schema、版本化历史、回归测试

HL 框架 + 完整工具系统 + 严格评估 = ICSE/ASE Tool Demo 级别的贡献。

---

## 8. 目标会议

**首选：** ICSE 2027 或 ASE 2027 Tool Demo Track
（TradeSweep 就是 ICSE 2025 Tool Demo——同一 track，同一社区）

---

## 9. 时间线

| 阶段 | 周期 | 交付物 |
|------|------|--------|
| Phase 1: 摄入 | Week 1-3 | PDF 解析、分块、embedding、向量存储 |
| Phase 2: 事实抽取 | Week 4-6 | 结构化抽取、证据跨度、per-topic schema |
| Phase 3: 查询与综合 | Week 7-8 | 多文档 RAG、对比、矛盾检测 |
| Phase 4: 自生长 | Week 9-10 | 增量更新、变化分类、历史压缩 |
| Phase 5: 评估 | Week 11-14 | Ground truth、自动化评估、用户研究、纵向试点 |
| Phase 6: 论文写作 | Week 15-18 | 系统描述、结果分析、相关工作 |

---

## 10. 待解决问题

1. **PDF 解析器选型：** pdfplumber → marker-pdf / docling / grobid？
2. **向量数据库：** LanceDB（嵌入式）vs ChromaDB（更成熟）vs pgvector？
3. **事实 schema 设计：** 完全 per-topic？还是共享核心 + per-topic 扩展？
4. **压缩触发机制：** 逐篇触发？每周触发？用户触发？
5. **如何评估 HL？** 如何测量"系统随时间变好"？纵向答案质量 vs KB 年龄？
6. **模型选择：** DeepSeek（低成本）vs GPT/Claude（高质量）？
7. **论文合作者：** 需要找有 ICSE 经验的合作者吗？

---

## Reference

[1] Weng, J. (2026). *Learning Beyond Gradients.* Blog post.
    https://trinkle23897.github.io/learning-beyond-gradients/

[2] Lee, C.-T., Neeser, A., Xu, S., Katyan, J., Cross, P., Pathakota, S.,
    Norman, M., Simeone, J., Chandrasekaran, J., & Ramakrishnan, N. (2025).
    Can an LLM Find Its Way around a Spreadsheet? In *Proceedings of the
    IEEE/ACM 47th International Conference on Software Engineering (ICSE '25)*,
    pp. 294–306. IEEE Press. DOI: 10.1109/ICSE55347.2025.00101

[3] survey_agent source code and enrichment pipeline.
    https://github.com/StoodCoronet/survey_agent
