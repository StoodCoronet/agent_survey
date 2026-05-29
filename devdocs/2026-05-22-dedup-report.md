# Sub-topic 去重阶段性汇报

## 1. 执行概况

三档去重（core / related / adjacent）已全部跑完，基于 `abstract` 在 12 个 topic 粒度上做保守→激进的递进式去重。

| Scope | 输入（有 abstract） | 保留 | 剔除 | 未处理 | 保留率 |
|-------|---------------------|------|------|--------|--------|
| **core** | 602 | 598 | 4 | 0 | **99.3%** |
| **related** | 2,952 | 2,787 | 133 | 32 | **94.4%** |
| **adjacent** | 6,995 | 6,464 | 494 | 37 | **92.4%** |
| **合计** | 10,549 | 9,849 | 631 | 69 | **93.4%** |

- **core** 最保守：只剔除显而易见的 follow-up / minor extension（仅 4 篇）。
- **related** 中等：剔除 clear duplicate 和仅换数据集/指标的增量工作。
- **adjacent** 最激进：同一方法线仅保留 1 篇代表性工作，即使数据集不同也剔除。
- 未处理的 69 篇是因为没有 `topics_json` 标签，不参与 topic-group 去重，需后续补标签或手动 review。
- 三档之间无交集（core/related/adjacent 按 `relevance` 互斥），因此 **unique 保留总量 = 9,849 篇**。

---

## 2. 按 Topic 的去重效果

### 2.1 Core（最保守）

| Topic | 总量 | 保留 | 剔除 | 保留率 |
|-------|------|------|------|--------|
| app_general | 263 | 262 | 1 | 99.6% |
| test_benchmark | 182 | 180 | 2 | 98.9% |
| dataset_generation | 161 | 160 | 1 | 99.4% |
| arch_framework | 113 | 113 | 0 | 100% |
| test_generation | 48 | 48 | 0 | 100% |
| sec_defense | 33 | 32 | 1 | 97.0% |
| sec_attack | 29 | 29 | 0 | 100% |
| test_redteam | 15 | 14 | 1 | 93.3% |

Core 档整体保留率极高，只有 test_redteam 和 sec_defense 各有 1 篇被判定为过于 incremental 而剔除。

### 2.2 Related（中等）

| Topic | 总量 | 保留 | 剔除 | 保留率 |
|-------|------|------|------|--------|
| app_general | 986 | 948 | 38 | 96.1% |
| sec_attack | 662 | 622 | 40 | 94.0% |
| sec_defense | 638 | 613 | 25 | 96.1% |
| test_benchmark | 593 | 573 | 20 | 96.6% |
| test_generation | 349 | 331 | 18 | 94.8% |
| test_redteam | 288 | 265 | 23 | 92.0% |
| dataset_generation | 268 | 257 | 11 | 95.9% |
| arch_framework | 33 | 30 | 3 | 90.9% |

剔除主要集中在 `app_general`（38 篇）和 `sec_attack`（40 篇），说明这两个方向增量工作最多。`test_redteam` 保留率最低（92%），表明该方向方法同质化较严重。

### 2.3 Adjacent（最激进）

| Topic | 总量 | 保留 | 剔除 | 保留率 |
|-------|------|------|------|--------|
| app_general | 3,314 | 3,116 | 198 | 94.0% |
| arch_framework | 1,504 | 1,384 | 120 | 92.0% |
| test_benchmark | 1,261 | 1,205 | 56 | 95.6% |
| dataset_generation | 828 | 802 | 26 | 96.9% |
| sec_defense | 744 | 662 | 82 | 89.0% |
| sec_attack | 201 | 186 | 15 | 92.5% |
| test_redteam | 96 | 85 | 11 | 88.5% |
| test_generation | 45 | 36 | 9 | 80.0% |
| mechanistic_interpretability | 31 | 26 | 5 | 83.9% |
| ai_governance_and_alignment | 22 | 4 | 18 | 18.2% |

Adjacent 档剔除最狠的方向：
- `ai_governance_and_alignment` 仅保留 18.2%（4/22），说明该 topic 下大量 paper 与 AI Agent 安全/测试关联度弱，被 aggressive dedup 扫掉。
- `test_generation` 保留率 80%（最低），同一测试生成方法在不同代码库上的重复应用被大量剔除。
- `sec_defense` 保留率 89%，防御方法同质化严重。

---

## 3. 按会议/venue 的保留分布

### Core（保留 598 篇）

| Venue | 保留数 |
|-------|--------|
| EMNLP | 100 |
| ACL | 93 |
| AAAI | 82 |
| CHI | 61 |
| ICLR | 54 |
| ICML | 46 |
| NeurIPS | 45 |
| NAACL | 32 |
| ASE | 29 |
| UIST | 16 |
| ICSE | 13 |
| TOSEM | 7 |
| TSE | 5 |
| FSE | 4 |
| NDSS | 4 |

Core 档以 AI/NLP/HCI 会议为主（EMNLP/ACL/AAAI/CHI 占 336 篇），SE/Security 核心 venue 占 62 篇。

### Related（保留 2,787 篇）

| Venue | 保留数 |
|-------|--------|
| ICSE | 314 |
| EMNLP | 311 |
| ASE | 284 |
| AAAI | 280 |
| ACL | 267 |
| TSE | 209 |
| TOSEM | 162 |
| ICLR | 141 |
| NAACL | 121 |
| NeurIPS | 120 |
| ICML | 115 |
| FSE | 102 |
| CCS | 76 |
| CHI | 73 |
| NDSS | 54 |

Related 档 SE venue 占比显著提升：ICSE + ASE + TSE + TOSEM + FSE = 1,071 篇（38.4%），说明去重前 SE 方向在 related 层有大量的积累。

### Adjacent（保留 6,464 篇）

| Venue | 保留数 |
|-------|--------|
| AAAI | 1,427 |
| EMNLP | 897 |
| CHI | 853 |
| ICLR | 790 |
| ACL | 733 |
| ICML | 636 |
| NeurIPS | 595 |
| NAACL | 242 |
| UIST | 137 |
| ASE | 52 |
| FSE | 41 |
| ICSE | 18 |
| TOSEM | 18 |
| COLM | 9 |
| CCS | 6 |

Adjacent 以 AI 顶会为主（AAAI/EMNLP/CHI/ICLR/ACL/ICML/NeurIPS 占 5,431 篇，84.0%），SE/Security venue 极少，符合预期。

---

## 4. 技术实现回顾

### 4.1 Pipeline 架构
- **Stage A**：sub-topic 发现，按 topic 分组，每批 20 篇 paper，LLM 标注细粒度 sub-topic。
- **Stage B**：在 `(topic, sub-topic)` 组内做去重，每批 20 篇，LLM 判断保留/剔除。
- **Venue bias**：SE/Security venue 保守保留，AI/NLP/HCI venue 激进剔除。
- **Scope 递进**：core（仅 core paper）→ related（仅 related paper）→ adjacent（仅 adjacent paper），三档独立互不影响。

### 4.2 执行过程中的 bug 修复
1. **related/adjacent 跳过 bug**：core 跑完后 `sub_topics_json` 已写入 DB，导致 related/adjacent 的 Stage A `where_a` 过滤为空，`topic_groups_b` 为空。修复：当 `topic_groups_b` 为空时，直接从 DB 加载已有 `sub_topics_json` 构建 Stage B 分组。
2. **fallback 被覆盖 bug**：`rows_a` 有 69 篇 straggler（无 `topics_json`）导致 `_run_stage_a` 返回空的 `paper_subtopics`，覆盖了 fallback 数据。修复：仅在 Stage A 实际产出结果时才覆盖 fallback。

### 4.3 资源消耗

| Scope | Stage B API Calls | Tokens | 预估费用 |
|-------|-------------------|--------|----------|
| core | ~30 | ~190K | ~$0.03 |
| related | 198 | 1,355,854 | ~$0.21 |
| adjacent | 411 | 2,587,770 | ~$0.41 |
| **合计** | **~639** | **~4.1M** | **~$0.65** |

---

## 5. 下一步建议

1. **处理未处理论文**：69 篇无 `topics_json` 的论文需补 topic 标签（`classify-topics --force` 或手动 review）。
2. **决定下载策略**：
   - **保守策略**：只下载 core 的 598 篇 + related 的 2,787 篇 = **3,385 篇 PDF**。
   - **激进策略**：三档全下 = **9,849 篇 PDF**（量极大，建议进一步筛选）。
   - **折中策略**：core + related + adjacent 中 SE/Security venue 的论文优先下载。
3. **Sub-topic 精细化**：当前 Stage A 的 sub-topic 粒度在 related/adjacent 跑时因 fallback 逻辑显示为 `uncategorized`（实际 dedup 按 topic 粒度执行）。如需更细粒度的 sub-topic 标签，可重新跑一遍全量 Stage A 并修复 fallback 覆盖问题。
4. **进入 deepdive**：基于选定 scope 的保留论文，启动 `fulltext` 下载 PDF，随后 `deepdive` 做结构化提取（方法、数据集、指标、局限）。
