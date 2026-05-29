# 分类树草案 v1 — 供 review

## Tree 1: 应用场景树 (Application Domain)

```
application-domain/
├── web-agent/
│   ├── web-navigation          # 网页浏览、点击、表单填写
│   ├── web-shop                # 电商购物、比价
│   ├── web-information-seeking # 信息检索、问答
│   └── web-task-automation     # 跨网站任务自动化
├── mobile-agent/
│   ├── android-agent           # Android 设备控制
│   ├── ios-agent               # iOS 设备控制
│   └── cross-platform-mobile   # 跨平台移动端
├── desktop-agent/
│   ├── os-agent                # 操作系统级控制 (OSWorld 类)
│   ├── gui-application-agent   # 桌面 GUI 应用控制
│   └── code-ide-agent          # IDE 内代码操作 (Cursor/Copilot 类)
├── code-agent/
│   ├── code-generation         # 代码生成/补全
│   ├── code-repair             # bug 修复、程序修复
│   ├── test-generation         # 测试用例生成
│   └── repo-level-agent        # 仓库级代码理解/修改
├── embodied-agent/
│   ├── robot-manipulation      # 机器人操作
│   ├── vision-language-navigation  # VLN
│   └── game-playing-agent      # 游戏 AI (Minecraft 等)
└── multi-domain-agent/         # 跨域通用 agent
```

## Tree 2: 技术方法树 (Technical Approach)

```
technical-approach/
├── planning/
│   ├── llm-planning            # ReAct, CoT, ToT 等规划
│   ├── symbolic-planning       # PDDL / 符号规划
│   └── hierarchical-planning   # 分层规划 (HRL)
├── learning/
│   ├── rl-based                # 强化学习训练 (PPO, DQN)
│   ├── imitation-learning      # 模仿学习 / 行为克隆
│   └── self-improvement        # 自我改进 / 自举
├── tool-use/
│   ├── function-calling        # 函数调用 / API 调用
│   ├── tool-learning           # 工具学习和发现
│   └── retrieval-augmented     # RAG / 知识检索增强
├── multi-agent/
│   ├── collaborative-agent     # 协作多智能体
│   ├── competitive-agent       # 竞争/博弈多智能体
│   └── role-playing-agent      # 角色扮演 (如 CAMEL)
├── perception/
│   ├── gui-grounding           # GUI 元素定位/理解
│   ├── vision-language-model   # VLM 视觉理解
│   └── web-page-understanding  # 网页 DOM/视觉理解
├── memory/
│   ├── episodic-memory         # 情景记忆
│   ├── semantic-memory         # 语义/知识记忆
│   └── long-context            # 长上下文窗口利用
└── safety-alignment/
    ├── guardrail               # 输入/输出防护
    ├── human-in-the-loop       # 人在回路
    └── constrained-generation  # 约束生成
```

## Tree 3: 研究目标树 (Research Goal)

```
research-goal/
├── benchmark-evaluation/
│   ├── new-benchmark           # 提出新 benchmark
│   ├── comprehensive-evaluation # 多模型系统评测
│   └── ablation-study          # 消融实验分析
├── attack-redteam/
│   ├── jailbreak-attack        # 越狱攻击
│   ├── prompt-injection        # 提示注入攻击
│   ├── adversarial-manipulation # 对抗操控
│   └── automated-redteaming    # 自动化红队测试
├── defense-security/
│   ├── prompt-defense          # 提示防御/过滤
│   ├── agent-sandboxing        # 沙箱/隔离
│   ├── monitoring-detection    # 监控与异常检测
│   └── privacy-protection      # 隐私保护
├── framework-system/
│   ├── agent-architecture      # 新 agent 架构设计
│   ├── tool-ecosystem          # 工具生态/平台
│   └── workflow-orchestration  # 工作流编排
├── dataset-resource/
│   ├── training-dataset        # 训练数据构建
│   ├── synthetic-data          # 合成数据生成
│   └── annotation-tool         # 标注工具
└── analysis-survey/
    ├── taxonomy-survey         # 分类/综述
    ├── failure-analysis        # 失败案例分析
    └── capability-assessment   # 能力边界评估
```
