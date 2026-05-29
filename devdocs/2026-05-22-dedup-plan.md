# Deepdive 前论文去重方案（Spec）

## 1. 背景与目标

- 已完成 topic 分类：core 635 篇 + related 3,249 篇 = 3,884 篇候选进入 deepdive
- AI/NLP venues 论文高度密集，存在大量方法相似、仅应用场景不同的论文
- 目标：通过 LLM 细分类 + 去重，将候选集压缩到约 500 篇（跨 topic 独立计数，实际唯一论文约 300-400 篇）

## 2. 核心原则

- **按 topic 独立判断**：一篇论文在 topic A 被删、在 topic B 被留，是允许的。最终 deepdive 以论文粒度去重。
- **只用 LLM，不做 embedding**：利用 LLM 对内容的深层理解，batch 内直接判断系列工作。
- **保守去重**：同一场景 + 同一方法 = 重复；研究问题（challenge）不同 = 保留。
- **保留策略**：core 优先，同等级别比年份（新 > 旧）。

## 3. 技术方案：两轮 Batch LLM

### Stage A：自动细分类（Sub-topic Discovery）

对每个 seed topic（8 个）分别执行：

1. 提取该 topic 下所有 core + related 论文（按年份排序）
2. 拆分为 batch，每批 20-25 篇
3. **LLM Prompt**：读该 batch 的全部 title + abstract，输出每篇论文的 sub-topic 标签
   - sub-topic 由 LLM 在该 batch 内自动归纳（如 `test_benchmark` 下出现 `code_benchmark`、`GUI_agent_eval`、`security_redteaming_eval` 等）
   - 输出格式：JSON，每篇论文一个 sub-topic 字符串
   - 要求 LLM 尽量复用已有的 sub-topic 名称，减少碎片化
4. 收集所有 batch 的 sub-topic 标签，做全局归一化（去重、合并近似名称）
5. 按 (topic, sub-topic) 重组论文

**调用量**：3,884 篇 / 25 ≈ 155 次 LLM 调用

### Stage B：Sub-topic 内去重

对每个 (topic, sub-topic) 组分别执行：

1. 提取该组内所有论文
2. 拆分为 batch，每批 20-25 篇（组内论文少的可能一批就够）
3. **LLM Prompt**：读该 batch 的全部 title + abstract，输出保留决策
   - 要求 LLM 识别"同一系列工作"（same scene + same method）
   - 如果 challenge/research question 不同，即使方法相似也保留
   - 每簇保留 1 篇：core > related，同年份级别取更新的
   - 输出格式：JSON，保留列表 + 去重理由
4. 收集所有保留决策，汇总为该 (topic, sub-topic) 下的保留论文 ID 列表

**调用量**：取决于 sub-topic 数量。假设 8 个 topic 各拆成 5-8 个 sub-topic，共约 50 个 sub-topic 组，平均每组 50 篇，每组 2-3 个 batch，总计约 120-150 次调用。

**总调用量**：Stage A (~155) + Stage B (~135) ≈ **290 次 LLM 调用**，用 deepseek-chat（Flash），预估成本 <$3。

## 4. 输出与汇报

去重全部完成后，生成一份 Markdown 汇报（`output/dedup/dedup_report.md`）：

- 每个 topic 的去重前后对比（原始 core+related 数 → 保留数）
- 每个 topic 下的 sub-topic 分布及保留数
- 被去重的典型论文对示例（保留谁、删除谁、理由）
- 最终汇总：跨 topic 保留的唯一论文数 vs 跨 topic 计数

## 5. DB Schema 变更

新增列或复用现有列：
- `sub_topics_json TEXT`：存储 LLM 分配的 sub-topic 标签（列表，和 topics_json 对齐）
- `stage_status_json` 中新增 `subtopic_dedup` 状态标记

## 6. CLI 集成

新增命令：
```bash
agent-survey dedup \
  --limit 0 \
  --batch-size 25 \
  --workers 2 \
  --model deepseek-chat
```

支持：
- `--dry-run`：只跑 Stage A（细分类），输出生成的 sub-topics 供 review
- `--force`：重新跑（覆盖已有 sub-topic 标签）

## 7. 风险提示

- LLM 对 "same scene + same method" 的判断存在主观性，汇报中会附典型 case 供人工抽查
- sub-topic 名称可能在不同 batch 间不一致，需要全局归一化（可用 simple string similarity 或人工 review）
- 跨 topic 论文会被多次判断，最终 deepdive 以论文粒度去重，不受此影响
