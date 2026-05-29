# Agent Survey — Topic Classification 阶段性汇报

> 日期：2026-05-22
> 阶段：Stage 6 (Topic Classification) 完成
> 数据范围：73,703 篇论文（2023–2026，SE/Security/AI venues）

---

## 一、总体概况

| 指标 | 数值 | 说明 |
|------|------|------|
| 总论文数 | 73,703 | 已 harvest 全部 venues |
| 有 abstract | 10,549 | 覆盖率 14.3%（arXiv/S2/Web 综合 enrichment） |
| 已完成 relevance 分类 | 73,703 | Stage 3 (classify) 已完成 |
| **core** | 635 | 直接相关，高质量 |
| **related** | 3,249 | 间接相关，有一定关联 |
| **adjacent** | 7,576 | 边缘相关，背景参考 |
| **irrelevant** | 62,243 | 无关 |
| 已完成 topic 分类 | **10,480 / 10,549** | **覆盖率 99.3%** |

未覆盖的 69 篇多为 adjacent/related 但与 agent 测试/安全距离较远的论文，LLM 未匹配任何 topic 且未建议新建，属正常现象。

---

## 二、Topic 分类体系与分布

当前体系由 **8 个 seed topics** + **4 个 auto-created topics** 构成。

### 2.1 全量对比表

| Topic (ID) | 中文名 | 总论文 | core | related | adjacent | Top 3 来源会议 | 2023→2025 增长 | 一句话洞察 |
|------------|--------|--------|------|---------|----------|----------------|----------------|------------|
| **sec_attack** | Agent 攻击 | 892 | 29 | 662 | 201 | AAAI(168) EMNLP(134) ACL(122) | 89→405 (4.5x) | 2025 爆发，但 91% 在 AI/NLP 顶会，安全 venue 渗透率仍低 |
| **sec_defense** | Agent 防御与安全 | 1,415 | 33 | 638 | 744 | AAAI(274) EMNLP(199) ICML(150) | 133→620 (4.7x) | 体量最大 security topic，但 core 仅 2.3%，大量论文是"提及安全" |
| **test_benchmark** | Agent 基准与评估 | 2,036 | 182 | 593 | 1,261 | AAAI(323) ACL(314) EMNLP(308) | 218→923 (4.2x) | **核心支柱**，core 比例高（28.7%），AI/NLP 顶会主导 |
| **test_redteam** | Agent 红队测试 | 399 | 15 | 288 | 96 | EMNLP(76) AAAI(75) ACL(44) | 27→196 (7.3x) | **增长最快**，但 core 仅 15 篇，方法论仍处早期 |
| **test_generation** | Agent 测试生成 | 442 | 48 | 349 | 45 | **ICSE(87) ASE(78) TSE(51)** | 80→204 (2.6x) | **最纯粹的 SE topic**，近 90% 来自 SE/Security venues，AI venues 极少 |
| **arch_framework** | Agent 架构与框架 | 1,650 | 113 | 33 | 1,504 | AAAI(408) EMNLP(327) ACL(224) | 182→717 (3.9x) | adjacent 占 91%，大量论文"使用架构"而非"研究架构" |
| **app_general** | Agent 通用应用 | 4,563 | 263 | 986 | 3,314 | CHI(854) AAAI(776) EMNLP(542) | 628→1,786 (2.8x) | **体量最大**（43.5%），但 adjacent 占 72.6%，是"泛 agent 论文"收容所；CHI 贡献最多 |
| **dataset_generation** | 数据集与基准生成 | 1,257 | 161 | 268 | 828 | ACL(238) AAAI(231) EMNLP(223) | 126→591 (4.7x) | **最硬核** topic（core 率 12.8%），NLP venues 贡献近 50% |

> **核心指标速览**
> - 8 个 topic 总覆盖 10,480 篇论文（支持多标签，单篇可跨 topic）
> - Core 论文共 635 篇，其中 Testing 方向 204 篇 vs Security 方向 23 篇（约 9:1）
> - 所有 topic 均在 2025 年达到峰值，2026 年数据不全

---

### 2.2 Security vs Testing 聚焦（Core 论文）

| 类型 | Core 论文数 | 说明 |
|------|-------------|------|
| 纯 Testing 方向 | 204 | benchmark + redteam + test_generation + dataset_generation |
| 纯 Security 方向 | 23 | attack + defense |
| Security + Testing 交叉 | 29 | 同时命中 security 和 testing topic |

> **洞察**：Testing 方向的 core 论文数量显著多于 Security（约 9:1），说明当前学术界在 agent 测试/评测/数据集构建方面的研究更为活跃。Security 方向仍有较大挖掘空间，尤其在 red teaming 和 attack 方面。

---

### 2.3 Auto-created Topics

| ID | 英文名 | 中文名 | 论文数 | 评估 |
|----|--------|--------|--------|------|
| `mechanistic_interpretability` | Mechanistic Interpretability | 机制可解释性 | 32 | ⚠️ 偏 general ML，待定 |
| `ai_governance_and_alignment` | AI Governance & Alignment | AI 治理与对齐 | 23 | ⚠️ 偏宏观治理，建议删除 |
| `pretraining_dynamics` | Pretraining Dynamics | 预训练动态 | 15 | ⚠️ 偏 general ML，建议删除 |
| `weak-to-strong_generalization` | Weak-to-Strong Generalization | 弱到强泛化 | 2 | ⚠️ 偏 general ML，建议删除 |

> **建议**：后三个 auto-created topic 明显偏向通用机器学习，与本次 survey 聚焦方向关联度较低，建议从 `taxonomy.json` 中移除。

---

## 三、Venue 覆盖与质量

所有主要 venue 的 topic 覆盖率均超过 **95%**：

| Venue | 覆盖率 | 特点 |
|-------|--------|------|
| AAAI | 99.0% | AI 综合，各 topic 均衡 |
| EMNLP | 99.8% | NLP 顶会，app_general + benchmark 密集 |
| ACL | 99.7% | NLP 顶会，dataset_generation 最强 venue |
| CHI | 99.8% | HCI 顶会，app_general 第一大来源 |
| ICLR | 99.3% | AI 顶会，architecture + security 活跃 |
| ICML | 99.9% | AI 顶会，security 增长快 |
| NeurIPS | 99.7% | AI 顶会，benchmark + security |
| NAACL | 100% | NLP 顶会，覆盖率最高 |
| ASE | 100% | **SE 顶会，test_generation 第二大来源** |
| ICSE | 95.0% | **SE 顶会，test_generation 第一大来源** |
| TSE | 100% | SE 期刊，test_generation 第三大来源 |
| TOSEM | 95.1% | SE 期刊，testing 应用 |
| FSE | 100% | SE 顶会，testing 方向 |
| UIST | 100% | HCI 顶会，app_general |
| CCS | 100% | **Security 顶会，test_generation + attack** |
| USS | 100% | **Security 顶会，attack 方向** |
| NDSS | 100% | Security 顶会，安全方向 |
| SP | 100% | Security 顶会，安全方向 |

---

## 四、年份趋势（Core + Related）

| Topic | 2023 | 2024 | 2025 | 2026 |
|-------|------|------|------|------|
| app_general | 194 | 357 | 547 | 151 |
| test_benchmark | 94 | 209 | 378 | 94 |
| dataset_generation | 46 | 112 | 226 | 45 |
| sec_attack | 73 | 208 | 310 | 100 |
| sec_defense | 69 | 198 | 312 | 92 |
| test_redteam | 22 | 83 | 152 | 46 |
| test_generation | 78 | 102 | 185 | 32 |
| arch_framework | 3 | 36 | 83 | 24 |

> **洞察**：
> 1. **2025 年是爆发年**：几乎所有 topic 的 core+related 论文数在 2025 年达到峰值（app_general 547 篇、test_benchmark 378 篇、sec_attack 310 篇）。
> 2. **Security 增长迅猛**：sec_attack 和 sec_defense 从 2023 年的 ~70 篇增长到 2025 年的 ~310 篇，增幅约 4.5 倍。
> 3. **Testing 稳步增长**：test_benchmark 和 test_generation 持续上升，说明 agent 评测和测试生成已成为稳定的研究主线。
> 4. **2026 年数据不全**：当前仅收集到部分 2026 年论文（AAAI/CHI/NDSS/SP/TOSEM 等），数据不完整，不宜直接对比。

---

## 五、多标签情况

| 类型 | 论文数 | 占比 |
|------|--------|------|
| 单标签 | 8,308 | 79.3% |
| 多标签（≥2 个 topic） | 2,172 | 20.7% |

多标签主要出现在以下交叉组合：
- `test_benchmark` + `dataset_generation`（评测基准和数据集生成高度关联）
- `sec_attack` + `test_redteam`（攻击和红队测试方法论重叠）
- `arch_framework` + `app_general`（架构研究与应用场景结合）

---

## 六、发现与总结

### 7.1 主要发现

1. **数据质量高**：10,480 / 10,549 篇已完成 topic 分类，覆盖率 99.3%。
2. **Testing > Security**：当前学术界在 agent 测试/评测/数据集构建方面的研究远多于安全方向。
3. **2025 年爆发**：agent 安全与测试研究在 2025 年出现显著增长，可能与 GPT-4 级 agent 落地、SWE-bench/OSWorld 等 benchmark 的推动有关。
4. **SE venues 是测试主力**：ASE、ICSE、FSE、TSE 等 SE  venue 的 related/core 论文高度集中在 testing 方向，是本次 survey 测试类论文的核心来源。
5. **Security venues 渗透率低**：USS、CCS、NDSS、SP 等安全顶会中 agent 安全论文数量仍然较少（USS 仅 3 篇 core），说明 agent 安全研究在安全社区尚未成为主流。

### 7.2 问题与建议

| 问题 | 建议 |
|------|------|
| 4 个 auto-created topic 偏向 general ML | 删除 `pretraining_dynamics`、`weak-to-strong_generalization`、`ai_governance_and_alignment`，保留 `mechanistic_interpretability` 待定 |
| 69 篇论文无 topic | 可手动 review，确认是否补充标签或保持空白 |
| abstract 覆盖率仅 14.3% | 后续 deepdive 阶段（Stage 5）需重点获取 core/related 论文的 PDF 全文 |

---

## 七、下一步

1. **清理 taxonomy**：移除无关 auto-created topics，更新 `taxonomy.json`
2. **Stage 4 (Fulltext)**：下载 core + related 论文的 arXiv PDF
3. **Stage 5 (Deepdive)**：对 PDF 进行结构化信息抽取（方法、实验、结论）
4. **Stage 7 (Report)**：生成 Obsidian vault + Markdown survey

---

*报告生成时间：2026-05-22*
*数据来源：`output/db/papers.sqlite`、`output/taxonomy/taxonomy.json`*
