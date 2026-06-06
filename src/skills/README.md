# Heuristic Learning Skill System

## 概念

传统爬虫在网站结构变化时会失效。这个 skill 系统把我们在构建 survey_agent 过程中积累的**决策流程**沉淀为可复用的 procedure，让 agent（人或 AI）能够：

1. **诊断** — 哪个 venue 的哪个阶段出了问题？
2. **探测** — 有哪些可用的数据源？逐一测试
3. **选择** — 找到有效的策略并固定下来
4. **积累** — 策略表随使用不断增长

```
┌──────────────┐    probe    ┌──────────────┐    select    ┌──────────────┐
│ source_probe │───────────→│   strategy    │───────────→│  persistence  │
│  (探测数据源) │            │  (选择策略)    │            │  (策略表更新)  │
└──────────────┘            └──────────────┘            └──────────────┘
       ↑                          │                            │
       │     feedback loop        │                            │
       └──────────────────────────┴────────────────────────────┘
              "上次这个策略能跑通，这次试试行不行"
```

## 已实现的 Skills

### Python skill modules（运行时 playbook dict）

| Skill | 类别 | 触发条件 |
|-------|------|---------|
| `harvest_strategy` | harvest | venue-year 返回 0 篇或 harvest 报错 |
| `enrich_strategy` | enrich | venue 的 abstract 覆盖率 < 80% |
| `source_probe` | adapt | 数据源返回错误或新 venue 需要选源 |
| `playwright_scrape` | adapt | 静态 HTTP 失败，页面是 JS 渲染的 |
| `consistency_check` | validate | 报表生成前或任何 pipeline stage 之后 |

### Anthropic-style agent skills（folder-based SKILL.md）

这些 skill 采用 [Anthropic skills](https://github.com/anthropics/skills) 的目录结构：每个 skill 是一个文件夹，入口为 `SKILL.md`，可选 `scripts/`、`references/`、`assets/` 等 bundled resources。

```
skill-name/
├── SKILL.md          # YAML frontmatter + Markdown instructions
├── scripts/          # (optional) 可执行脚本
├── references/       # (optional) 参考资料
└── assets/           # (optional) 模板、图标等
```

| Skill | 路径 | 触发条件 |
|-------|------|---------|
| `core-download` | [`core-download/SKILL.md`](core-download/SKILL.md) | arXiv/S2/OpenReview 拿不到 PDF 时，用 CORE API v3 发现和下载 |
| `crossref-resolve` | [`crossref-resolve/SKILL.md`](crossref-resolve/SKILL.md) | 需要权威 DOI、元数据或出版商链接；尤其适合非 CS 期刊 |

Python skills 通过 `from skills import get_skill` 加载；Markdown agent skills 直接供 Claude / 其他 AI agent 在阅读 `SKILL.md` 后按步骤执行。

## 使用方式

```python
from skills import get_skill, list_skills

# 查看所有可用 skill
print(list_skills())
# → ['consistency_check', 'enrich_strategy', 'harvest_strategy', 'playwright_scrape', 'source_probe']

# 获取 skill 定义
skill = get_skill("harvest_strategy")
print(skill["description"])
print(skill["steps"])

# Agent 执行 (future)
# result = agent.execute(skill["name"], venue="FSE", year=2024)
```

## Skill 结构

每个 skill 文件定义：

```python
SKILL = {
    "name": "skill_name",           # 唯一标识
    "version": "1.0",
    "category": "harvest|enrich|validate|adapt",
    "description": "...",           # 一句话描述
    "trigger": "...",               # 什么时候触发
    "inputs": {...},                # 输入参数 schema
    "outputs": {...},               # 输出结构 schema
    "steps": [...],                 # 步骤列表 (human-readable)
    "fallback_chain": [...],        # 退化链路
    "thresholds": {...},            # 决策阈值
    "integration_points": "...",    # 代码集成点
}
```

## 启发式学习循环

```
┌─────────────────────────────────────────────────────┐
│                  Iteration Loop                      │
│                                                      │
│  10-paper probe  →  full run  →  gap analysis  →  refine
│  (快速验证策略)     (全量执行)    (找出遗漏)      (补充策略)
│                                                      │
│  e.g. S2 测10篇 ✓8  → 全量跑完 → ACL Anthology     │
│       够了,先上线      发现遗漏3%   补充兜底          │
└─────────────────────────────────────────────────────┘

Pipeline 运行
    ↓
某个 venue 失败 / 覆盖率不足
    ↓
触发对应 skill (如 enrich_strategy)
    ↓
Agent 按 skill procedure 逐步探测 (10 paper probe)
    ↓
找到有效策略 → 更新策略表
    ↓
全量 enrich 执行
    ↓
Post-run gap analysis: 按 (venue, source, failure_pattern) 聚类
    ↓
├─ 某 source 对某 venue 大片失效 → re-probe, 可能网站变了
├─ 特定年份集中失败 → 那年 proceedings 换平台了
├─ 零星失败 → 论文本身的问题 (proceedings volume, 撤稿等)
    ↓
Refine 策略 → 更新策略表 → 下次全量覆盖率提升
```

这个循环让系统**逐次逼近最优策略组合**，每次失败都是一次学习机会，策略表就是系统的"经验"。10-paper probe 保证快速迭代，post-run gap analysis 保证不遗漏长尾。

## 与 Agent 的关系

Skill 定义了 **what to do**（做什么），Agent 负责 **how to do**（怎么做）。

例如 `harvest_strategy` 的 step 1 是"探测 DBLP XML TOC"：
- **Skill**: 定义这个步骤存在，给出 URL 模板和成功条件
- **Agent**: 实际执行 curl 请求，解析 XML，判断是否成功，必要时尝试变体 URL

## 未来方向

- **Auto-heal**: 当 `consistency_check` 发现问题时，自动触发对应的 strategy skill
- **Skill chaining**: 多个 skill 串联执行（如 harvest_strategy → enrich_strategy 对新建 venue 的完整流程）
- **Strategy versioning**: 当一个 venue 的策略变更时，记录历史策略以便回溯
- **Shared registry**: 允许社区贡献新的 venue 策略和 selector 模式
