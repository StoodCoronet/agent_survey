# 增量分类体系设计

## 核心关注
- **Agent 安全**（攻击、防御、隐私、越狱、对齐）
- **Agent 测试**（Benchmark、红队测试、测试生成、评估方法）
- 只要是和 agent 相关的都收（不限 code/gui/web agent）
- 性能/效率类不是重点

## 种子主题（初始状态）

```yaml
seed_topics:
  - id: sec_attack
    name: "Agent Attack"
    name_zh: "Agent 攻击"
    desc: "越狱、提示注入、对抗攻击、数据投毒、后门攻击"

  - id: sec_defense
    name: "Agent Defense & Safety"
    name_zh: "Agent 防御与安全"
    desc: "安全防护、对齐、隐私保护、恶意行为检测、可信计算"

  - id: test_benchmark
    name: "Agent Benchmark & Evaluation"
    name_zh: "Agent 基准与评估"
    desc: "能力评测基准、安全性评估、数据集构建、指标设计"

  - id: test_redteam
    name: "Agent Red Teaming"
    name_zh: "Agent 红队测试"
    desc: "自动化攻击发现、漏洞挖掘、对抗性测试、渗透测试"

  - id: test_generation
    name: "Agent Test Generation"
    name_zh: "Agent 测试生成"
    desc: "自动化生成测试用例、测试场景、测试数据、模糊测试"

  - id: arch_framework
    name: "Agent Architecture & Framework"
    name_zh: "Agent 架构与框架"
    desc: "系统架构、记忆管理、规划推理、工具调用、多智能体协作"

  - id: app_general
    name: "Agent General Application"
    name_zh: "Agent 通用应用"
    desc: "非测试/非安全的其他 agent 应用场景（代码生成、GUI 操作、Web 自动化等）"

  - id: dataset_generation
    name: "Dataset & Benchmark Generation"
    name_zh: "数据集与基准生成"
    desc: "为评测或解决 agent 问题而专门构建的数据集、基准、评测环境"
```

## 增量处理流程

```
输入：一批论文（5-10篇，标题+abstract）
    │
    ▼
LLM 输出每篇论文的：
  - 匹配的种子主题列表（多标签，0-1 分数）
  - 是否需要创建新子主题（附 parent_id + 理由 + 置信度）
    │
    ▼
Agent 决策：
  - 置信度 ≥ 0.8 的新主题 → 自动创建
  - 置信度 < 0.8 的新主题 → 标记为 "pending_review"，写入待审队列
  - 已有主题匹配 → 直接打标签
    │
    ▼
持久化：
  - taxonomy.json（树形结构，含 id/name/parent/children/papers_count）
  - papers_tags.json（每篇论文的标签列表）
    │
    ▼
人工后处理（可选）：
  - review pending 主题（合并/重命名/删除）
  - 调整标签分配
```

## LLM Prompt 要点

每批输入：
```
现有主题列表（带 ID 和描述）
---
论文1: [title]
[abstract]

论文2: ...
```

期望输出（JSON）：
```json
{
  "papers": [
    {
      "paper_id": "xxx",
      "tags": [
        {"topic_id": "sec_attack", "score": 0.92},
        {"topic_id": "test_redteam", "score": 0.75}
      ]
    }
  ],
  "new_topics": [
    {
      "parent_id": "sec_attack",
      "name": "Prompt Injection",
      "name_zh": "提示注入",
      "reason": "多篇论文聚焦 prompt injection 攻击",
      "confidence": 0.95,
      "paper_ids": ["p1", "p2"]
    }
  ]
}
```

## 数据结构

### taxonomy.json
```json
{
  "version": 1,
  "topics": {
    "sec_attack": {
      "id": "sec_attack",
      "name": "Agent Attack",
      "name_zh": "Agent 攻击",
      "parent_id": null,
      "children": ["sec_attack_prompt_injection"],
      "paper_count": 42,
      "created_at": "2026-05-20",
      "source": "seed"
    }
  }
}
```

### papers_tags.json
```json
{
  "papers": {
    "dblp://conf/sp/2023/xxx": {
      "tags": ["sec_attack", "test_benchmark"],
      "classified_at": "2026-05-20T10:00:00Z"
    }
  }
}
```

## CLI 命令

```bash
# 增量分类现有论文（按 batch_size 分批处理）
agent-survey classify-topics --batch-size 10 --limit 100

# 只看 pending 的新主题建议
agent-survey topics --pending

# review 后确认/拒绝 pending 主题
agent-survey topics --review

# 重新生成 taxonomy.json 和 papers_tags.json
agent-survey topics --export
```

## 成本估算

- 每批 10 篇 ≈ 800 token in / 400 token out
- 10k 篇 ≈ 1000 批 ≈ $2-3（DeepSeek Flash）
- 比单篇处理省 5-10 倍
