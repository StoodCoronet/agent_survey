# 分类树草案 v2 — 整合用户反馈

## 设计原则

1. **多棵分类树并存**，每棵树是一个独立分类依据（principle）
2. **子分类跨树复用**：性能 / 测试 / 攻击 / 防御 / benchmark 是"横切关注点"，可以在任意树的叶子节点下出现
3. **增量发现**：先手动定义骨架（2-3 层），LLM 在 deepdive 过程中可自动在叶子下发现新子类
4. **DeepResearch 独立成类**：作为一种需要大量工具调用、长链条推理的特殊 agent 形态

---

## Tree 1: 应用场景树 (Application Domain)

```
application-domain/
├── web-agent/
│   ├── web-navigation          # 网页浏览、点击、表单填写
│   ├── web-shop                # 电商购物、比价
│   ├── web-information-seeking # 信息检索、问答
│   ├── web-task-automation     # 跨网站任务自动化
│   └── web-h5-hybrid           # 移动端 H5 / WebView 混合应用
├── mobile-agent/
│   ├── android-native          # Android 原生应用控制
│   ├── ios-native              # iOS 原生应用控制
│   └── mobile-cross-platform   # 跨平台（Flutter / React Native / H5）
├── desktop-agent/
│   ├── os-level-control        # 操作系统级控制 (OSWorld 类)
│   ├── gui-app-control         # 桌面 GUI 应用控制
│   └── code-ide-integration    # IDE 内代码操作 (Cursor / Copilot 类)
├── code-agent/
│   ├── code-generation         # 代码生成/补全
│   ├── code-repair             # Bug 修复、程序修复
│   ├── test-generation         # 测试用例生成
│   └── repo-level-understanding# 仓库级代码理解/修改
├── embodied-agent/
│   ├── robot-manipulation      # 机器人操作
│   ├── vision-language-navigation  # VLN
│   └── game-playing-agent      # 游戏 AI (Minecraft 等)
├── scientific-research-agent/  # 科研助手
│   ├── literature-review       # 文献综述
│   ├── experiment-design       # 实验设计
│   └── data-analysis           # 数据分析
├── creative-agent/             # 创意生成
│   ├── content-generation      # 内容生成
│   └── design-assistant        # 设计辅助
└── multi-domain-agent/         # 跨域通用 agent
```

### 应用场景树的横切子分类（可在任意叶子下出现）

每个叶子节点下，论文可以进一步按以下维度归类：

```
[任意应用] /
├── performance                 # 性能优化、延迟、吞吐、资源消耗
├── testing-verification        # 测试用例生成、验证、可靠性
├── attack-redteam              # 对该场景的攻击/红队测试
├── defense-security            # 对该场景的防御/安全加固
└── benchmark-dataset           # 该场景的 benchmark 或数据集构建
```

---

## Tree 2: 技术方法树 (Technical Approach)

```
technical-approach/
├── planning/
│   ├── llm-planning            # ReAct, CoT, ToT 等规划
│   ├── symbolic-planning       # PDDL / 符号规划
│   └── hierarchical-planning   # 分层规划 (HRL)
├── learning/
│   ├── rl-based                # 强化学习训练
│   ├── imitation-learning      # 模仿学习 / 行为克隆
│   └── self-improvement        # 自我改进 / 自举
├── tool-use/
│   ├── function-calling        # 函数调用 / API 调用
│   ├── tool-learning           # 工具学习和发现
│   └── retrieval-augmented     # RAG / 知识检索增强
├── multi-agent/
│   ├── collaborative-agent     # 协作多智能体
│   ├── competitive-agent       # 竞争/博弈多智能体
│   └── role-playing-agent      # 角色扮演
├── perception/
│   ├── gui-grounding           # GUI 元素定位/理解
│   ├── vision-language-model   # VLM 视觉理解
│   └── web-page-understanding  # 网页 DOM/视觉理解
├── memory/
│   ├── episodic-memory         # 情景记忆
│   ├── semantic-memory         # 语义/知识记忆
│   └── long-context            # 长上下文窗口
├── deep-research/              # 深度研究型 agent
│   ├── tool-chain-orchestration# 工具链编排（调用多个 harness）
│   ├── iterative-verification  # 迭代验证与事实核查
│   └── multi-source-synthesis  # 多源信息综合
└── safety-alignment/
    ├── guardrail               # 输入/输出防护
    ├── human-in-the-loop       # 人在回路
    └── constrained-generation  # 约束生成
```

### 技术方法树的横切子分类

```
[任意技术] /
├── performance                 # 该技术方向的性能优化
├── testing-verification        # 该技术的测试/验证方法
├── attack-vulnerability        # 针对该技术的攻击/漏洞
├── defense-mitigation          # 针对该技术的防御/缓解
└── benchmark-evaluation        # 该技术的 benchmark / 评估
```

---

## Tree 3: 研究目标树 (Research Goal)

```
research-goal/
├── benchmark-evaluation/
│   ├── new-benchmark           # 提出新 benchmark
│   ├── comprehensive-evaluation # 多模型系统评测
│   └── ablation-study          # 消融实验
├── attack-redteam/
│   ├── jailbreak-attack        # 越狱攻击
│   ├── prompt-injection        # 提示注入
│   ├── adversarial-manipulation# 对抗操控
│   └── automated-redteaming    # 自动化红队
├── defense-security/
│   ├── prompt-defense          # 提示防御/过滤
│   ├── agent-sandboxing        # 沙箱/隔离
│   ├── monitoring-detection    # 监控与异常检测
│   └── privacy-protection      # 隐私保护
├── framework-system/
│   ├── agent-architecture      # 新 agent 架构
│   ├── tool-ecosystem          # 工具生态/平台
│   └── workflow-orchestration  # 工作流编排
├── dataset-resource/
│   ├── training-dataset        # 训练数据
│   ├── synthetic-data          # 合成数据
│   └── annotation-tool         # 标注工具
└── analysis-survey/
    ├── taxonomy-survey         # 分类/综述
    ├── failure-analysis        # 失败案例
    └── capability-assessment   # 能力边界评估
```

---

## 论文分类表示例

一篇论文可以同时属于多个树的多个节点：

| 论文 | 应用场景 | 技术方法 | 研究目标 | 横切子分类 |
|------|----------|----------|----------|-----------|
| OSWorld | `desktop-agent/os-level-control` | `perception/gui-grounding` | `benchmark-evaluation/new-benchmark` | benchmark, performance |
| SWE-bench | `code-agent/repo-level-understanding` | `tool-use/function-calling` | `benchmark-evaluation/new-benchmark` | benchmark, testing-verification |
| 某越狱攻击论文 | `web-agent/web-navigation` | `safety-alignment/guardrail` | `attack-redteam/jailbreak-attack` | attack |
| DeepResearch (OpenAI) | `scientific-research-agent/literature-review` | `deep-research/tool-chain-orchestration` | `framework-system/agent-architecture` | performance |

---

## 下一步实现方案

1. **DB Schema**: `taxonomy_json` 列存储论文的分类路径列表
2. **Pipeline**:
   - 先用 LLM 根据 abstract+全文 做第一层粗分类（到 2-3 层）
   - deepdive 过程中根据提取内容做第二层细分类（横切子分类）
   - 支持增量：遇到不属于现有分类的论文，LLM 提议新分类，人工确认后加入
3. **VitePress 展示**:
   - 每棵树一个导航菜单
   - 论文卡片显示所有分类路径
   - 支持按任意分类路径筛选
