# 关键词筛选报告：Agent Harness Context Management 视角

## 筛选原则

**保留标准**：关键词必须直接关联 **agent 系统层面的上下文管理**，而非底层模型优化。

**删除标准**：纯模型架构（位置编码、注意力机制）、纯推理优化（KV cache、量化）、纯评测基准。

---

## 一、Context Window and Position Encoding → ❌ 大部分删除

| 关键词 | 判断 | 理由 |
|--------|------|------|
| context window extension | ⚠️ 调整 | agent 需要长上下文，但"extension"偏模型训练/推理技术。建议改为 **"long-context agent"** 或 **"agent context window management"** |
| length extrapolation | ❌ 删除 | 纯模型位置编码技术，和 agent harness 无关 |
| position interpolation | ❌ 删除 | 同上 |
| length generalization | ❌ 删除 | 同上 |
| rotary position embedding (RoPE) | ❌ 删除 | 纯模型底层实现 |
| ALiBi | ❌ 删除 | 同上 |
| NTK-aware interpolation | ❌ 删除 | 同上 |
| YARN | ❌ 删除 | 同上 |
| position bias | ⚠️ 调整 | agent 中的位置偏差有价值，但需限定为 **"position bias in agent reasoning"** |
| lost-in-the-middle problem | ✅ 保留 | **agent 处理长文档/长历史时的核心问题**，直接影响 agent context management |
| attention sink | ❌ 删除 | 模型推理现象，非 agent 系统层面 |
| position encoding scaling | ❌ 删除 | 模型技术 |

**结论**：该类别的 12 个关键词中，**仅保留 1 个**（lost-in-the-middle），其余删除或调整。

---

## 二、KV Cache Optimization → ❌ 整类删除

| 关键词 | 判断 | 理由 |
|--------|------|------|
| KV cache compression | ❌ 删除 | 底层推理显存优化，和 agent context management 无关 |
| KV cache quantization | ❌ 删除 | 同上 |
| KV cache eviction | ❌ 删除 | 同上 |
| low-bit quantization | ❌ 删除 | 同上 |
| post-training quantization | ❌ 删除 | 同上 |
| token merging | ❌ 删除 | 模型推理优化 |
| flash attention compatibility | ❌ 删除 | 同上 |
| grouped-query attention compatibility | ❌ 删除 | 同上 |

**结论**：**整类删除**。这是纯推理工程优化，不属于 agent harness 的 context management 范畴。

---

## 三、Retrieval-Augmented Generation (RAG) → ⚠️ 大幅调整

| 关键词 | 判断 | 理由 |
|--------|------|------|
| retrieval-augmented generation (RAG) | ⚠️ 调整 | 通用 RAG 概念，需限定为 **"RAG for agents"** 或 **"agent knowledge retrieval"** |
| in-context learning | ❌ 删除 | 模型能力概念，非 agent 系统架构 |
| many-shot in-context learning | ❌ 删除 | 同上 |
| open-domain question answering | ❌ 删除 | 通用 NLP 任务，不特指 agent |
| multi-document question answering | ⚠️ 调整 | agent 需要多文档处理，但应聚焦于 **"agent multi-document context"** |
| retrieval-based techniques | ⚠️ 调整 | 过于宽泛，建议改为 **"agent memory retrieval"** |
| external memory retrieval | ✅ 保留 | **agent 外部记忆检索是核心概念**，直接相关 |
| retrieval augmentation | ⚠️ 调整 | 通用概念，建议明确为 **"retrieval augmentation for agent memory"** |

**结论**：8 个中 **仅保留 1 个**（external memory retrieval），其余需调整表述以限定 agent 场景。

---

## 四、Attention Mechanisms and Efficient Transformers → ❌ 整类删除

| 关键词 | 判断 | 理由 |
|--------|------|------|
| sparse attention | ❌ 删除 | 纯模型架构优化 |
| linear attention | ❌ 删除 | 同上 |
| flash attention | ❌ 删除 | 同上 |
| efficient transformer | ❌ 删除 | 同上 |
| decoder-only transformer | ❌ 删除 | 模型架构 |
| linear complexity attention | ❌ 删除 | 模型优化 |
| blockwise sparse attention | ❌ 删除 | 同上 |
| hybrid attention (convolutions, Mamba) | ❌ 删除 | 同上 |

**结论**：**整类删除**。全部是模型架构/效率优化，和 agent harness 无关。

---

## 五、Long-Context Evaluation and Benchmarks → ❌ 整类删除

| 关键词 | 判断 | 理由 |
|--------|------|------|
| long-context evaluation | ❌ 删除 | 评测方法论，非 agent context management 本身 |
| needle-in-a-haystack test | ❌ 删除 | 具体评测任务 |
| LongBench | ❌ 删除 | 评测基准 |
| L-Eval | ❌ 删除 | 同上 |
| passkey retrieval | ❌ 删除 | 评测任务 |
| single-document question answering | ❌ 删除 | 通用 NLP 任务 |
| multi-document question answering | ❌ 删除 | 通用 NLP 任务 |
| long-context benchmark | ❌ 删除 | 评测基准 |
| time-to-first-token (TTFT) | ❌ 删除 | 性能指标 |

**结论**：**整类删除**。全部是评测/指标，不是 agent context management 的核心概念。

---

## 六、Memory and Compression Techniques → ✅ 核心保留，需微调

| 关键词 | 判断 | 理由 |
|--------|------|------|
| context compression | ✅ 保留 | **agent 上下文压缩是核心问题** |
| prompt compression | ✅ 保留 | **agent prompt 压缩是核心问题** |
| memory compression | ✅ 保留 | **agent 记忆压缩，直接相关** |
| long-term memory | ✅ 保留 | **agent 长期记忆是核心架构** |
| working memory | ✅ 保留 | **agent 工作记忆是核心架构** |
| short-term memory | ✅ 保留 | **agent 短期记忆，相关** |
| hierarchical summarization | ✅ 保留 | **agent 多级摘要管理上下文，相关** |
| token pruning | ❌ 删除 | 偏底层模型优化，非 agent 系统层面 |

**结论**：8 个中 **保留 7 个**，仅删除 token pruning。

---

## 七、缺失的 Agent-Specific 关键词

当前 219 篇论文中 agent-specific 的比例可能不高，导致自动提取**遗漏了 agent harness 的核心概念**：

| 缺失关键词 | 重要性 |
|-----------|--------|
| **agent memory architecture** | 🔴 核心 |
| **multi-turn dialogue management** | 🔴 核心 |
| **prompt injection defense** | 🔴 核心 |
| **context-aware agent** | 🔴 核心 |
| **agent state management** | 🟡 重要 |
| **tool-use context / function calling context** | 🟡 重要 |
| **session-based context** | 🟡 重要 |
| **context switching** | 🟡 重要 |

---

## 八、最终建议

### 方案 A：直接删改现有 YAML（轻量）
- 删除 4 个整类（KV Cache、Attention、Evaluation、Position Encoding）
- 大幅精简 RAG 类
- 保留并强化 Memory and Compression 类
- **风险**：遗漏 agent-specific 概念，因为原始论文 agent 比例不高

### 方案 B：重新筛选论文子集 + 重新提取（准确）
- 从 219 篇中，用 LLM 判断哪些是 **agent-related survey**
- 只保留 agent-related 的 subset（可能只剩 50-100 篇）
- 对 subset 重新提取关键词 + 去重
- **优势**：关键词天然聚焦 agent harness

你倾向哪个方案？或者你想直接看我执行方案 A 的删改结果？
