# 实验评估方案：LLM安全对齐SoK

> **综述标题**: "LLM安全对齐：构建、攻破与防御——知识体系化研究"
> **状态**: 草案 v3 —— 多维度分类体系 + 全生命周期评估
> **日期**: 2026年7月15日
> **对标参考**: 仿照 *"Guardrails in the Crosshairs: A Systematic Evaluation of Safeguards Against LLM Jailbreak Attacks"*（SEU评估框架，6维度guardrail分类法）
> **数据库**: 1,196篇核心论文，91.6% PDF覆盖率，6棵树51个叶子节点

---

## 0. 分类体系总览：多维度分类系统

受参考论文6维度guardrail分类法的启发，我们重新设计了SoK的分类体系以覆盖完整的对齐生命周期。每篇论文在 **7个正交维度** 上进行标注，支持单棵树无法实现的跨维度分析。

### 维度全景图

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                         多维度分类体系（7个维度）                                           │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│  维度一：生命周期阶段（主轴）                                                               │
│  ├── 构建（Build）：对齐构建方法                                                           │
│  ├── 攻破（Break）：攻击方法                                                               │
│  ├── 防御（Defend）：防御策略                                                              │
│  ├── 理解（Understand）：脆弱性机制                                                        │
│  └── 度量（Measure）：评估与基准                                                           │
│                                                                                          │
│  维度二：技术范式                                                                          │
│  ├── 对齐方法：基于强化学习 / 直接偏好优化 / 博弈论 / 免训练 / 宪法式 / 数据中心式           │
│  ├── 攻击方法：基于优化 / 基于生成 / 手工 / 隐式 / 权重修改 / 激活操控                       │
│  └── 防御方法：基于规则 / 基于模型（ML/统计）/ 基于LLM                                     │
│                                                                                          │
│  维度三：对齐的干预层级（对齐在哪里被构建，在哪里被破坏）                                       │
│  ├── 权重级（Weight-level）：RLHF/DPO训练、有害微调、LoRA后门、模型合并——对齐在权重层面被构建/破坏 │
│  ├── 表示级（Representation-level）：激活引导、拒绝方向消融、神经元操控——对齐在表示层面被操控   │
│  ├── 提示级（Prompt-level）：系统指令、GCG后缀、角色扮演越狱——对齐在输入层面被绕过/注入         │
│  └── 输出级（Output-level）：解码干预、logit操控、输出精炼——对齐在输出层面被调整/劫持           │
│                                                                                          │
│  维度四：访问需求（适用性）                                                                  │
│  ├── 白盒（White-box）：需要模型权重/梯度/内部状态                                          │
│  ├── 灰盒（Gray-box）：需要输出logits/token概率                                            │
│  └── 黑盒（Black-box）：仅需API访问/文本输出                                               │
│                                                                                          │
│  维度五：部署阶段（干预时机）                                                                 │
│  ├── 部署前（Pre-deployment）：训练阶段、数据筛选、架构设计                                  │
│  ├── 推理中（At-inference）：预处理、内处理（前向传播）                                      │
│  └── 响应后（Post-response）：后处理、输出过滤                                              │
│                                                                                          │
│  维度六：分析粒度                                                                           │
│  ├── Token级：单个token、注意力头                                                          │
│  ├── 序列级（Sequence-level）：完整提示/响应对                                               │
│  ├── 会话级（Session-level）：多轮对话                                                     │
│  └── 模型级（Model-level）：架构、训练机制、规模                                            │
│                                                                                          │
│  维度七：模态范围                                                                           │
│  ├── 纯文本（Text-only）：纯语言模型                                                         │
│  ├── 视觉-语言（Vision-Language）：图像+文本输入                                             │
│  └── 多模态（Multimodal）：音频、视频、代码、结构化数据                                      │
│                                                                                          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

> **💡 维度三核心洞察**：对齐并非仅在训练时一次性完成。对齐的"构建"与"破坏"在四个层级（权重级/表示级/提示级/输出级）同时存在，形成一场多层级的攻防战。即使权重层面做了RLHF/DPO对齐，表示层/提示层/输出层仍可能被攻击。**这正是我们SoK试图回答的核心问题——post-training安全对齐到底有多脆弱？**

### 与参考论文的对比

| 参考论文（仅Guardrails） | 我们的SoK（全生命周期） |
|---|---|
| **维度1**: 干预阶段（前/中/后处理） | → 扩展为5阶段（增加训练阶段+解码阶段） |
| **维度2**: 技术范式（规则/ML/LLM式） | → 扩展至对齐+攻击的技术范式 |
| **维度3**: 安全粒度（Token/序列/会话） | → 增加模型级粒度用于架构分析 |
| **维度4**: 反应性（静态/动态） | → 并入部署阶段+技术范式维度 |
| **维度5**: 适用性（白盒/黑盒） | → 增加灰盒用于logit级访问 |
| **维度6**: 可解释性（不透明/可解释） | → 作为跨维度标签 |
| *参考论文未覆盖* | **维度7**: 模态范围（文本/VLM/多模态） |

### 各领域论文分布

| 领域（Domain） | 核心论文数 | 占比 |
|--------|------------|------------|
| 对齐构建（Alignment Construction） | 507 | 42.4% |
| 提示级攻击（Prompt-Level Attack） | 218 | 18.2% |
| 评估与红队（Evaluation & Red Teaming） | 141 | 11.8% |
| 鲁棒训练防御（Robust Training Defenses） | 84 | 7.0% |
| 脆弱性机制（Mechanisms of Fragility） | 83 | 6.9% |
| 参数级攻击（Parameter-Level Attack） | 64 | 5.4% |
| 运行时守卫（Runtime Guardrails） | 54 | 4.5% |
| 表示级攻击（Representation-Level Attack） | 45 | 3.8% |
| **总计** | **1,196** | **100%** |

---

## 1. 评估框架

> ⚠️ 本节为启发式草案。各指标的具体定义后续系统扫文章后补充，当前仅作定性描述。

我们的 SoK 核心问题是**"对齐到底有多脆弱？"**。评估框架围绕这个问题设计：在统一的 benchmark 上，测量各种加固手段（对齐方法、防御方法）在遭受各种攻击前后的 safety 和 utility 变化，同时记录加固和攻击各自的 efficiency 代价。

### 1.1 框架流程

```
Step 0: 应用加固手段 ────── 测 Efficiency
    │                     （训练GPU时间、数据量、推理延迟、显存开销）
    ▼
Step 1: Benchmark 基准 ──── 测 Safety + Utility baseline
    │                     （加固后模型在攻击前的表现）
    ▼
Step 2: 施加攻击 ────────── 测攻击的 Efficiency
    │                     （查询次数、优化迭代、所需样本量、是否需要白盒）
    ▼
Step 3: Benchmark 重测 ──── 测 Safety + Utility 变化
                          （攻击后的表现 vs baseline，差值即脆弱性）
```

### 1.1.1 调研总览

基于对 **1,106 篇论文**（96 篇精读 + 1,010 篇全量关键词扫描）的系统调研：

**Benchmark 使用排名**

```
安全评估                              效用评估
────────────────────────────────────────────────────
AdvBench       172 篇 (17.0%)         MMLU            157 篇 (15.5%)
HarmBench       78 篇 (7.7%)          AlpacaEval      154 篇 (15.2%)
Beavertails     65 篇 (6.4%)          HH-RLHF         108 篇 (10.7%)
XSTest          58 篇 (5.7%)          MT-Bench        107 篇 (10.6%)
JailbreakBench  34 篇 (3.4%)          GSM8K           103 篇 (10.2%)
ToxiGen         24 篇 (2.4%)          TruthfulQA       89 篇 (8.8%)
WildGuard       20 篇 (2.0%)          RewardBench      48 篇 (4.8%)
```

**模型使用排名**

```
GPT-4      610 篇 (60%)   Mistral    321 篇 (32%)   Llama-3    298 篇 (30%)
GPT-4o     279 篇 (28%)   Qwen       259 篇 (26%)   Llama-2    229 篇 (23%)
GPT-3.5    195 篇 (19%)   Vicuna     185 篇 (18%)   Claude     151 篇 (15%)
```

**指标使用排名**

```
ASR         500 篇 (50%)    FPR         503 篇 (50%)
困惑度       154 篇 (15%)    Win Rate    115 篇 (11%)
攻击成功率     99 篇 (10%)    拒绝率       38 篇 (4%)
```

**效率数据**: 仅 18.6% 论文提及。**300 篇高分论文**待精读。

**精读覆盖**：加固手段 24/24 类 ✓，攻击手段 17/17 类 ✓。详细调研日志见 `devdocs/research-methodology/`。

### 1.1.2 分类体系细化

基于 96 篇精读论文的分析，将"加固手段"重新划分为**对齐构建**（Build——让模型变安全）和**安全加固**（Harden——让已对齐的模型不被攻破），与攻击手段形成三层体系。

#### 对齐构建（Build — 让模型变安全）

> 量大类别（RLHF、DPO、安全微调）已细分至第三层，标注了优化目标和安全相关代表作。

```
偏好优化 (344篇 DB)
  RLHF/PPO (134篇) — 奖励模型 + PPO 强化学习
    ├── 改进策略优化
    │   PPO 训练不稳定、安全优化信号弱 → 改损失函数/优化过程
    │   · WALKSAFE: 把输入建模成语义图，随机游走量化风险，Bi-GRPO替代PPO
    │   · SDGO: 让LLM同时做"鉴别器"和"生成器"，缩小两者安全判断差距
    ├── 改进奖励/数据
    │   偏好数据缺乏安全维度标注、单轮训练无法应对多轮攻击
    │   · PKU-SafeRLHF: 构建安全偏好数据集，把 helpfulness 和 harmlessness 分开标注
    │   · MTSA: 多轮红队实时生成对抗样本，训练模型在多轮对话中保持安全
    ├── 理论分析
    │   RLHF 为什么有效/失效？什么条件下对齐会崩溃？
    │   · Jailbreaking as Reward Misspecification (ICLR 2025): 越狱本质是奖励函数没覆盖到的区域
    │   · Unified Analysis (ICML 2025): 噪声标签对RLHF/DPO对齐效果的理论界限
    └── 特定场景安全
        新架构/新模态出现时，RLHF 是否仍然有效？
        · dLLM safety: 扩散语言模型的安全对齐——RLHF在非自回归架构上的首次研究
  DPO 变体 (190篇) — 无需奖励模型，直接从偏好数据学习
    ├── 多目标安全 DPO
    │   DPO 一次只优化一个偏好维度，安全+有用无法兼得
    │   · SPA: 强制"先安全、后有用"的优先级排序，安全约束下优化有用性
    │   · Sequential PO: 把多维度偏好拆成序列，逐个优化，不需要多个reward model
    ├── 鲁棒 DPO
    │   偏好标注有噪声、会翻转、会被投毒 → DPO 训练被污染
    │   · Preference Flip: 实例相关鲁棒损失，自动降权可疑的偏好标注
    │   · AutoMixAlign: 自适应混合 helpful+harmless+honest 三类数据比例
    └── DPO 用于防御
        能否用偏好优化的思路直接防御攻击？
        · SecAlign (CCS 2025): 用DPO训练模型遵守"任务对齐"，抵抗间接提示注入
        · MPO (ACL 2025): 多语言安全对齐，缩小不同语言间的安全差距
  多目标对齐 (35篇) — 同时优化安全性+有用性等多个维度
    ├── 帕累托优化 (8篇)   在多个目标间找帕累托前沿 → ParetoHqD (高质量帕累托数据)
    │                     Robust Multi-Objective DPO (在线DPO+可变权重)
    ├── 多价值/多元对齐 (23篇) 处理不同人群/文化的价值冲突 → Pluralistic Values (多元价值观权衡)
    │                     FGD-Align (模糊群决策), Multi-Value Alignment (价值解耦)
    └── 顺序/维度分解 (5篇)  把多维偏好拆成序列逐步优化 → Sequential PO (隐式奖励建模)
                          Magic-Token (可切换安全控制)
  Nash 博弈 (10篇) — 将对齐建模为博弈均衡

免训练对齐 (99篇)
  解码时对齐 (73篇) — 不改模型权重，在推理阶段干预输出
    ├── 对比解码
    │   同时计算"安全路径"和"不安全路径"的logit分布，用差值引导输出
    │   · ACD (AAAI 2026): 对抗对比解码，优化出安全/对抗两个软prompt做对比
    │   · DeAL (ACL 2025): 把对齐目标直接嵌入解码过程，不需额外模型
    ├── 测试时在线优化
    │   推理时用轻量优化器在线调整输出分布，类似微型DPO但不更新权重
    │   · LLMdoctor (AAAI 2026): token级流引导偏好优化，测试时对齐
    │   · Nudging (ACL 2025): 引导解码，在推理时把base model输出向aligned方向推
    ├── 表示操控
    │   推理时直接干预内部激活向量，把有害表示转向安全方向
    │   · SCANS (AAAI 2025): 安全感知激活引导，缓解过度拒绝
    │   · Multi-Attribute Steering (ACL 2025): 多属性可操控引导
    └── 前缀/分布引导
        修改prompt前缀或直接调整logit分布来约束安全边界
        · Prefix Detoxification (AAAI 2026): 自适应前缀启发式引导解毒
        · SDA (AAAI 2026): 引导驱动分布对齐，不改权重实现多领域适配
  提示引导 (26篇) — 通过系统提示约束行为

规则驱动对齐 (26篇)
  Constitutional AI (12篇) — AI 反馈替代人类标注
  原则驱动对齐 (14篇) — 显式编码价值原则

数据中心式 (143篇)
  偏好数据筛选 (105篇) — 数据质量决定安全水平
    ├── 质量过滤          怎么挑出"好"的偏好对 → 长度偏差消除, RewardBench 评估, 高质量帕累托数据
    ├── 冲突/去噪         标注有矛盾、偏好翻转怎么办 → 冲突感知框架, 偏好翻转检测
    └── 多样性覆盖        数据是否代表足够多元的人类价值 → 文化安全, 多元价值观权衡
  合成偏好生成 (68篇) — AI 生成偏好数据
    ├── 自对弈/自进化      模型自己生成偏好数据→自己评估→迭代训练 → Beyond Human Data, SMPRO
    ├── AI 标注/评判       用另一个 LLM 打分/排序生成偏好标签 → Generative Reward Modeling
    └── 数据增强/衍生      从现有偏好变换出更多样本 → HumorReject (幽默拒绝数据)
  偏好投毒鲁棒 (7篇) — 偏好数据被投毒攻击时，对齐能否保持？
    攻击: 攻击者污染RLHF/DPO的偏好标注 (RLHFPoison: 收买标注者上调有害回复排名)
    防御: 检测/抵抗被污染的偏好数据 (PoisonBench: 首个偏好投毒基准)
    发现: DPO 比 PPO 更易被投毒 (没有 reward model 这层缓冲)
  Weak-to-Strong (13篇) — 弱监督训练强模型
```

#### 安全加固（Harden — 不让已对齐被攻破）

```
训练时加固 (233篇)
  安全保持微调 (134篇) — 微调下游任务时保持安全
    ├── 安全退化机制      Incomplete Safety Learning (诊断:安全特征天然在浅层，微调最先破坏它)
    │                    AsFT (安全盆地:正交于对齐方向的扰动即触发退化)
    ├── 新型安全微调范式    HumorReject (幽默替代拒绝前缀)
    │                    Magic-Token (推理时可切换安全开关)
    └── 小模型/高效安全    EASE (小语言模型的实用安全对齐)
                         STAR-1 (1K数据实现推理模型安全对齐)
  对抗训练 (43篇) — 训练时注入对抗样本，但"对抗什么"各不相同
    ├── 抗有害微调        攻击者修改模型权重 → AntiDote (双层对抗), Vulnerability-Aware (脆弱性感知)
    ├── 抗越狱 prompt      攻击者构造恶意输入 → AGD (对抗博弈), Refusal Feature AT (拒绝特征训练)
    ├── 抗后门攻击        攻击者植入隐藏触发器 → BEEAR (基于嵌入的后门对抗移除)
    ├── 抗遗忘/重学习     攻击者恢复被删除的知识 → Robust Unlearning (锐度感知最小化)
    └── 多模态/数据/表示   各种专项场景 → Q-MLLM (VLM), Data to Defense (数据筛选), Contrastive Repr (对比表示)
  防篡改训练 (14篇) — 专门防止有害微调/模型合并攻击
    ├── 模型免疫           让权重"免疫"有害微调 → TAR, Vaccine, Model Immunization
    ├── 对抗微调           训练时注入对抗样本提高鲁棒性 → AntiDote (双层), Booster
    └── 防合并/自退化      防模型合并攻击或自退化防御 → Do Not Merge, SDD
  Circuit Breakers       3篇 — 表示重路由，短接有害通路
  机器遗忘 (39篇) — 选择性擦除有害知识，不同方法在"怎么忘"和"忘什么"上分化
    ├── 遗忘方法        怎么高效擦除？→ ALTER (非对称LoRA), RMU (表示误导), Precise Erasure (参数级)
    ├── 遗忘鲁棒性      忘了还能恢复吗？→ Adversarial Unlearning (对抗查询恢复), SEUF (MoE遗忘)
    ├── 安全专项遗忘    忘掉什么？→ Constrained Knowledge Unlearning (只忘有害知识), Revoke Backdoors
    └── 跨模态/多语言    不同模态/语言怎么忘？→ Cross-Modal Unlearning (MLLM), Multilingual Unlearning

推理时加固 (141篇)
  激活引导 (63篇) — 推理时操控内部激活向量，不修改权重
    ├── 频谱/子空间过滤    用随机矩阵理论定位有害表示的"频道"并滤除 → EigenShield (降ASR 92.9%)
    │                    Bleeding Pathways (隐藏状态判别力消失分析)
    ├── 安全方向引导       在激活空间中找"安全方向"，把有害表示投射过去 → SCANS (缓解过度拒绝)
    │                    SDA (引导驱动分布对齐，多领域适配)
    ├── 多层检测树         构建层级安全分类器，逐层判断是否越狱 → AlignTree (高效树形防御)
    └── 动态适配           推理时动态调整引导策略 → Dynamic Prompt Optimization, SafeInfer
  解码干预 (52篇) — 修改解码策略，不依赖外部模型
    ├── 对比解码           同时计算安全/不安全两条路径的logit，用差值引导输出
    │                    · ACD (对抗对比解码), Contrastive Decoding for Code
    ├── 分布/前缀引导      直接调整输出logit分布或注入安全前缀 → Prefix Detox, LLMdoctor
    ├── 风险感知解码       解码时动态评估每一步的风险 → AURA (affordance风险感知)
    └── 专项场景解码       针对特定领域的安全解码 → MobileSafetyBench (agent), STaR (推理)
  精炼对齐器 (26篇) — 用额外的轻量模型修正主模型输出
    ├── 输出修正模型       训练小型对齐器，在推理时修正主模型的不安全输出
    │                    · AURA, CoT Adversarial Extrapolation
    ├── 测试时对齐         推理时做轻量偏好优化，类似微型DPO → LLMdoctor, Stream Aligner
    ├── 安全提醒注入       在生成过程中注入安全信号，唤醒模型的安全意识
    │                    · SafetyReminder (VLM), Path Drift (推理模型)
    └── 攻防对偶           利用攻击技术来防御 → Attack Techniques for Defense

Guardrail (119篇)
  预处理输入过滤 (53篇) — 在输入进入模型前拦截
    ├── 分类器式          训练二分类器判断有害/安全 → Llama Guard, WildGuard, Prompt Guard
    ├── 语义/图分析        解析输入语义结构发现隐藏攻击 → Semantic-Graph Defense
    ├── 统计/熵检测        用统计特征检测异常输入 → MirrorShield (熵引导), Perplexity Filter
    └── 专项场景过滤       RAG/VLM/身份保护等 → ShieldRAG, DAVSP
  内处理内部监控 (38篇) — 分析模型前向传播中的内部状态
    ├── 梯度分析           分析前向传播中的梯度信号 → GradSafe (安全关键梯度检测)
    ├── 注意力/表示监控     监控注意力头和内部表示 → AlignTree (多层树), ConfGuard (后门检测)
    └── 专项场景           特定架构/场景的内部监控 → PurMM (MLLM), Attention Defense (提示注入)
  后处理输出过滤 (28篇) — 在模型输出后拦截
    ├── LLM 评判           用另一个 LLM 评判输出是否安全 → Llama Guard, WildGuard
    ├── 扰动/一致性检测     对输出做扰动，检查一致性 → SmoothLLM, SemanticSmooth
    └── 专项输出过滤       特定模态/场景 → T2I-RiskyPrompt, MMJ-Bench (VLM)
```

#### 攻击方法（Break — 攻破对齐）

```
提示级 — 单轮 (200篇)
  优化式 GCG/AutoDAN (75篇) — 白盒 token 优化
    ├── 核心 GCG/梯度优化 (~25篇)   GCG 族算法改进、坐标上升变体、AutoDAN
    ├── 多模态对抗攻击 (~17篇)      GCG 扩展到 VLM/音频/医学 MLLM → StyleBreak, MMJ-Bench
    ├── 迁移/隐写/黑盒 (~12篇)      跨模型迁移、通用 suffix、黑盒代理攻击
    └── RAG/Agent 投毒 (~10篇)     GCG 攻击检索增强系统/LLM Agent → Joint-GCG, DUALBREACH
  生成式 PAIR (37篇) — 黑盒 LLM 生成，不需梯度
  手工角色扮演 (56篇) — 通过人格扮演/认知偏差/模板漏洞绕过
    ⚠ 分类噪声约30%，部分论文实为攻击防御/benchmark而非角色扮演，待清理
  隐写/编码/多语言 (25篇) — 密码, emoji, 低资源语言
  Many-shot (3篇) — 长上下文注入
  提示注入 (4篇) — 间接注入

提示级 — 多轮 (52篇)
  逐步升级 Crescendo (27篇) — 逐步诱导
  任务分解 ActorAttack (12篇) — 细粒度拆分
  多智能体 X-teaming (13篇) — 最强攻击，ASR>90%

参数级 (57篇)
  有害微调 (76篇) — 微调阶段的安全攻击
    ├── 后门注入 (~30篇)       微调时植入隐藏触发器 → Persistent Backdoor, Dormant Backdoor
    ├── 数据投毒 (~20篇)       污染 RLHF/DPO 偏好数据 → Cost-Minimized Poisoning, Scaling Trends
    ├── 良性微调退化 (~15篇)    无攻击者，正常微调也掉安全 → Agentic FT Misalignment
    └── 防御/净化 (~10篇)      微调阶段安全防护 → PurMM, Attention Head Realignment
  LoRA后门 (6篇) — PEFT 注入
  模型编辑 (13篇) — 知识编辑攻击
  权重操控 (15篇) — 模型合并攻击

表示级 (38篇)
  激活操控 (14篇)
  拒绝方向消融 (7篇) — 拒绝由单一方向介导
  Logit操控               6篇
  神经元抑制              3篇
```

#### 关键发现

1. **提示级攻击是红海**：GCG 和 PAIR 几乎是所有攻击论文的 baseline
2. **参数级攻击的威胁被低估**：有害微调论文数虽不如提示级，但破坏力 91.8% ASR
3. **多轮攻击是前沿**：X-teaming 对现有防御 ASR>90%
4. **输出级攻击几乎空白**：仅 6 篇 logit 操控论文
5. **没有完美防御**：EigenShield 降 ASR 92.9% 是最好成绩，仍有 7% 漏网
6. **效率-安全 tradeoff**：推理时防御更实用但引入延迟，训练时防御更彻底但成本高

### 1.2 四个测量环节

**Step 0 — 加固手段的 Efficiency**

部署对齐/防御的成本有多高？不同加固范式的代价差异是 SoK 的重要比较维度。

| 加固类型 | 想度量什么（定性） |
|---------|------------------|
| 训练时对齐（RLHF、DPO、CAI） | 训练 GPU 时间、偏好数据需求量 |
| 训练时防御（TAR、Circuit Breakers） | 额外训练开销、对原始训练流程的侵入性 |
| 推理时防御（EigenShield、AlignTree） | 推理延迟增量、GPU 显存增量 |
| 免训练对齐（RAIN、Prompt Steering） | 解码/提示层面的开销 |

**Step 1 — Safety + Utility 基准**

在攻击之前，加固后的模型表现如何？这是后续比较的基线，同时也是不同加固手段的横向对比。

| 维度 | 想度量什么（定性） |
|------|------------------|
| **Safety** | 在面对一组标准化有害输入时，模型拒绝/合规的比例。基准越高，说明加固越有效 |
| **Utility** | 在标准能力基准（知识、推理、对话）上的表现；是否存在过度拒绝——良性请求也被误判为有害 |

**Step 2 — 攻击的 Efficiency**

攻击的性价比直接决定其实用威胁。Qi et al. 的发现之所以震撼，正因为"$0.20 + 5步梯度"即可瓦解对齐。

| 维度 | 想度量什么（定性） |
|------|------------------|
| **成本** | 需要多少查询、多少训练样本、多少优化迭代、多少 GPU 时间？ |
| **访问需求** | 白盒（需要权重/梯度）、灰盒（需要 logits）、还是黑盒（仅需 API）？ |

**Step 3 — 攻击后的 Safety + Utility 变化**

这是脆弱性的核心度量。同一 benchmark 在攻击前后各测一次，差值即加固手段被"攻掉"的程度。

| 维度 | 想度量什么（定性） |
|------|------------------|
| **Safety 降幅** | 攻击后安全性下降了多少？是完全崩溃还是部分退化？不同加固方法面对同一攻击的降幅差异？ |
| **Utility 变化** | 攻击是否误伤了模型的正常能力？有些攻击（如有害微调）可能连带破坏通用性能 |
| **破坏模式** | 是全局性崩溃还是局部漏洞？只在某些类别的有害输入上失效还是全面失守？ |

### 1.3 三类实验对象

框架统一应用于三类对象，只是 Step 0 的"加固手段"不同：

| 对象 | Step 0 的加固 | 核心问题 |
|------|-------------|---------|
| **对齐构建方法** | RLHF / DPO / CAI / RAIN 等 | 不同对齐范式的抗攻击韧性有何差异？ |
| **防御方法** | TAR / Circuit Breakers / EigenShield 等 | 防御手段能否有效抵御指定攻击面？ |
| **裸模型（baseline）** | 无加固 | 未对齐的模型有多危险？（作为参照基线） |

### 1.4 攻击面的覆盖

需要覆盖不同层面的攻击，揭示对齐在哪个层级最脆弱：

| 攻击层面 | 代表方法 | 与框架的兼容性 |
|---------|---------|--------------|
| **权重级** | 有害微调、LoRA后门、模型编辑 | 攻击改变模型本身，Step 1 测原始、Step 3 测微调后的模型 |
| **提示级** | GCG、PAIR、Crescendo、Many-shot | 推理时注入，Step 1 不加攻击、Step 3 加上攻击测 |
| **表示级** | 拒绝方向消融、激活操控 | 推理时注入，兼容框架；白盒类攻击可能无法用到黑盒 benchmark 部分 |
| **输出级** | Logit 操控、强制解码 | 推理时注入，兼容框架 |

### 1.5 不兼容统一 Benchmark 的情况

某些攻击可能不方便纳入统一的 pre/post benchmark 对比：

| 情况 | 示例 | 替代方案 |
|------|------|---------|
| 多轮对话攻击 | Crescendo——单轮 benchmark prompt 无法体现逐步升级的机制 | 使用专门的多轮评估集（如 SafeMTData），但仍保持 pre/post 结构 |
| 跨语言/跨模态攻击 | 隐写术越狱、多语言越狱 | Benchmark 需扩展对应模态/语言的测试用例 |
| 攻击本身即训练过程 | 有害微调改变了模型权重 | Pre/post 仍然成立，只是"post"测的是微调后的新模型，而非推理时注入 |

**全局视图**: 参考 SaP 的做法，将 ASR 放在 X 轴、MMLU 放在 Y 轴，不同对齐/防御方法形成帕累托前沿——一目了然地展示 safety-capability tradeoff。

### 1.6 试点论文分析（20 篇）

为将框架从启发式草案落实为可执行方案，我们分析了 20 篇代表性论文（对齐 6 篇、攻击 6 篇、防御 4 篇、benchmark 4 篇），提取其 benchmark 使用协议、攻击超参配置和加固实现细节。

**Benchmark 现状**：

| 发现 | 细节 |
|------|------|
| **HarmBench 是最全面的安全 benchmark** | 510 种有害行为 × 4 功能类别 × 18 种攻击 × 33 个 LLM。ASR = 被分类器判定为触发了目标行为的测试用例占比 |
| **JailbreakBench 是评估协议最标准化的** | 100 种有害行为（10 类，对齐 OpenAI 使用政策），配对的良性行为用于过度拒绝检测。标准评判器：Llama-3-Instruct-70B |
| **没有同时覆盖 safety + utility 的 benchmark** | 论文各自组合：HarmBench/JailbreakBench/AdvBench 测 safety，MMLU/MT-Bench/AlpacaEval 测 utility。两个维度永远分开报告 |
| **协议共识**：贪婪解码（temperature=0）、GPT-4 或 Llama-3 做评判器、ASR 为主要指标 |

**攻击配置（可直接复用的超参）**：

| 攻击 | 论文来源 | 关键配置 |
|------|---------|---------|
| GCG | Zou et al. (2023)，被 20 篇中的 12 篇引用为 baseline | 500 iter，batch 512，单 prompt，贪婪解码 |
| AutoDAN | Liu et al. (ICLR 2024) | 分层遗传算法，500 iter，4 个开源模型 + GPT-3.5 |
| Many-shot | Anil et al. (NeurIPS 2024) | 256-shot 上下文注入 |
| Harmful FT | Qi et al. (ICLR 2024) | 10/50/100 shot，5 epoch，lr=5e-5，batch=10 |
| PAIR | Chao et al. (2023) | ~20 queries/attempt，黑盒，attacker=Mixtral-8×7B |

**加固实现细节**：

| 方法 | 论文 | 关键配置 |
|------|------|---------|
| DPO | Rafailov et al. (NeurIPS 2023) | 二值交叉熵，β 参数控制 KL 约束强度，无 reward model，比 PPO 简单 |
| RAIN | Li et al. (ICLR 2024) | 免训练：自评估+回退机制嵌入自回归推理。不需要额外模型，不存储梯度 |
| Circuit Breakers | Zou et al. (NeurIPS 2024) | 表示重路由损失 + 保留损失，训练时注入，推理时生效 |
| TAR | Tamirisa et al. (ICLR 2025) | 训练时获取安全向量，微调时对齐到该向量 |
| EigenShield | Darabi et al. (AAAI 2026) | 推理时频谱过滤，不需要模型重训练或内部访问 |

**我们的框架在文献中的独特性**：

| 文献中已有 | 文献中没有（= 我们的贡献） |
|-----------|------------------------|
| 攻击方法之间的 ASR 对比（HarmBench 已做） | 对齐构建方法之间的韧性对比（RLHF vs DPO vs CAI 在相同攻击下谁更耐打？） |
| 防御方法之间的 ASR 降幅对比（JailbreakBench 已做） | 加固→攻击→重测的完整 pre/post pipeline |
| Safety 和 utility 分别评估（每篇论文都做） | 统一 benchmark 下同时追踪 safety 和 utility 的 pre/post 变化 |
| 推理时防御的延迟开销（EigenShield 等做了） | 训练时对齐/防御的效率标准化度量（这在文献中几乎空白） |

---

## 2. 论文选取：叶子节点全覆盖

### 选取方法论
1. **覆盖率优先**: 每个叶子节点≥1篇
2. **质量过滤**: 优先顶会（ICLR/NeurIPS/ICML/ACL/CCS/USENIX/AAAI/NDSS）
3. **时效性**: 优先2024-2026年（仅基础性工作保留2023年）
4. **多样性**: 混合方法类型（攻击/防御/分析/基准）
5. **可复现性**: 优先开源权重的方法

### 总计：92篇论文，覆盖51个叶子节点

---

### 2.1 对齐构建（Build）—— 20篇，13个叶子

#### 偏好优化（preference-optimization）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| AC1 | **rlhf-ppo** | ⚠️ Ouyang et al., "Training Language Models to Follow Instructions with Human Feedback"（InstructGPT） | NeurIPS | 2022 | *需补充* |
| AC2 | **rlhf-ppo** | An et al., "MoralReason: Generalizable Moral Decision Alignment via Reasoning-Level RL" | AAAI | 2026 | `dblp:conf/aaai/AnD26` |
| AC3 | **dpo-variants** | Rafailov et al., "Direct Preference Optimization" | NeurIPS | 2023 | `dblp:conf/nips/RafailovSMMEF23` |
| AC4 | **dpo-variants** | Chen et al., "Preference Optimization via Contrastive Divergence" | AAAI | 2026 | `dblp:conf/aaai/ChenLZWLQG26` |
| AC5 | **multi-objective** | Gu et al., "ParetoHqD: Fast Offline Multiobjective Alignment" | AAAI | 2026 | `dblp:conf/aaai/GuWMZJ26` |
| AC6 | **nash-game-theoretic** | Choi et al., "Self-Improving Robust Preference Optimization" | ICLR | 2025 | `dblp:conf/iclr/ChoiAGPA25` |
| AC7 | **reward-modeling** | Huang et al., "Long-form RewardBench: Evaluating Reward Models for Long-form Generation" | AAAI | 2026 | `dblp:conf/aaai/HuangHLYLCXZCZ26` |

#### 数据中心式（data-centric）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| AC8 | **preference-data-curation** | Bhattacharyya et al., "ALPHA: Action-Based Learning for Pluralistic Human Alignment" | AAAI | 2026 | `dblp:conf/aaai/BhattacharyyaAS26` |
| AC9 | **preference-poisoning-robustness** | Fu et al., "PoisonBench: Assessing LLM Vulnerability to Poisoned Preference Data" | ICML | 2025 | `dblp:conf/icml/FuS0C0B25` |
| AC10 | **preference-poisoning-robustness** | Wang et al., "RLHFPoison: Reward Poisoning Attack for RLHF" | ACL | 2024 | `dblp:conf/acl/Wang0CVX24` |
| AC11 | **synthetic-preference-generation** | Huang et al., "SPA: Achieving Consensus via Self-Priority Optimization" | AAAI | 2026 | `dblp:conf/aaai/HuangWZ26` |
| AC12 | **weak-to-strong** | ⚠️ Burns et al., "Weak-to-Strong Generalization"（OpenAI） | arXiv | 2023 | *需补充* |
| AC13 | **weak-to-strong** | Lang et al., "Selective Weak-to-Strong Generalization" | AAAI | 2026 | `dblp:conf/aaai/LangHL26` |

#### 免训练（training-free）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| AC14 | **decoding-time-alignment** | Li et al., "RAIN: Your Language Models Can Align Themselves without Finetuning" | ICLR | 2024 | `dblp:conf/iclr/LiWZ0024` |
| AC15 | **decoding-time-alignment** | Shang et al., "From Chaos to Cure: Prefix Heuristics Guided Detoxification" | AAAI | 2026 | `dblp:conf/aaai/ShangCRWLLZH26` |
| AC16 | **prompt-based-steering** | Mahmud et al., "Inference-Aware Prompt Optimization for Aligning Black-Box LLMs" | AAAI | 2026 | `dblp:conf/aaai/MahmudNWZ26` |

#### 宪法/规则驱动（constitutional-rule-based）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| AC17 | **constitutional-ai** | ⚠️ Bai et al., "Constitutional AI: Harmlessness from AI Feedback" | arXiv | 2022 | *需补充* |
| AC18 | **constitutional-ai** | Wang et al., "STAR-1: Safer Alignment of Reasoning LLMs with 1K Data" | AAAI | 2026 | `dblp:conf/aaai/WangTWWLMBKX26` |
| AC19 | **principle-driven-alignment** | Xu et al., "Towards Better Value Principles for LLM Alignment: A Systematic Evaluation" | ACL | 2025 | `dblp:conf/acl/XuYYMX025` |
| AC20 | **principle-driven-alignment** | Ye et al., "Generative Psycho-Lexical Approach for Constructing Value Systems in LLMs" | ACL | 2025 | `dblp:conf/acl/YeZXZRZS25` |

---

### 2.2 攻击方法（Break）—— 28篇，17个叶子

#### 参数级攻击（parameter-level）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| AT1 | **harmful-fine-tuning** | Qi et al., "Fine-tuning Aligned Language Models Compromises Safety" | ICLR | 2024 | `dblp:conf/iclr/Qi0XC0M024` |
| AT2 | **harmful-fine-tuning** | Cui et al., "Persistent Backdoor Attacks Under Continual Fine-Tuning of LLMs" | AAAI | 2026 | `dblp:conf/aaai/CuiHJZ26` |
| AT3 | **lora-peft-attack** | Chen et al., "Causal-Guided Detoxify Backdoor Attack of Open-Weight LoRA Models" | NDSS | 2026 | `dblp:conf/ndss/ChenSWC26` |
| AT4 | **lora-peft-attack** | Liu et al., "ELBA-Bench: An Efficient Learning Backdoor Attacks Benchmark for LLMs" | ACL | 2025 | `dblp:conf/acl/LiuLH0LCHT25` |
| AT5 | **model-editing** | Chen et al., "Can Editing LLMs Inject Harm?" | AAAI | 2026 | `dblp:conf/aaai/ChenHLCLXGGYXYW26` |
| AT6 | **model-editing** | Huang et al., "Model Editing as a Double-Edged Sword" | AAAI | 2026 | `dblp:conf/aaai/HuangTWLLPLCS26` |
| AT7 | **weight-manipulation** | Wu et al., "NeuroStrike: Neuron-Level Attacks on Aligned LLMs" | NDSS | 2026 | `dblp:conf/ndss/WuBRTPS26` |
| AT8 | **weight-manipulation** | Li et al., "Do Not Merge My Model! Safeguarding Against Unauthorized Model Merging" | AAAI | 2026 | `dblp:conf/aaai/LiPCTSSPZ26` |

#### 单轮提示级攻击（prompt-level-single-turn）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| AT9 | **optimization-gcg-autodan** | ⚠️ Zou et al., "Universal and Transferable Adversarial Attacks"（GCG） | arXiv | 2023 | *需补充* |
| AT10 | **optimization-gcg-autodan** | Yang et al., "CoSPED: Consistent Soft Prompt Targeted Data Extraction and Defense" | AAAI | 2026 | `dblp:conf/aaai/YangFT26` |
| AT11 | **generation-pair-advprompter** | ⚠️ Chao et al., "Jailbreaking Black Box LLMs in Twenty Queries"（PAIR） | arXiv | 2023 | *需补充* |
| AT12 | **generation-pair-advprompter** | Diao et al., "SEAS: Self-Evolving Adversarial Safety Optimization for LLMs" | AAAI | 2025 | `dblp:conf/aaai/DiaoLLLWCX25` |
| AT13 | **manual-role-play** | Shen et al., "Do Anything Now: Characterizing In-The-Wild Jailbreak Prompts"（JailbreakHub） | CCS | 2024 | `dblp:conf/ccs/ShenC0SZ24` |
| AT14 | **manual-role-play** | Yang et al., "Exploiting Synergistic Cognitive Biases to Bypass Safety in LLMs" | AAAI | 2026 | `dblp:conf/aaai/YangZTHH26` |
| AT15 | **implicit-cipher-multilingual** | Li et al., "Odysseus: Jailbreaking Commercial Multimodal LLM via Dual Steganography" | NDSS | 2026 | `dblp:conf/ndss/LiCLJT26` |
| AT16 | **implicit-cipher-multilingual** | Cui et al., "When Smiley Turns Hostile: Interpreting How Emojis Trigger LLM Toxicity" | AAAI | 2026 | `dblp:conf/aaai/CuiFWYZSWQH26` |
| AT17 | **many-shot-jailbreaking** | Anil et al., "Many-shot Jailbreaking" | NeurIPS | 2024 | `dblp:conf/nips/AnilDPSBKBTMFMA24` |
| AT18 | **many-shot-jailbreaking** | Ma et al., "PANDAS: Improving Many-shot Jailbreaking via Positive Affirmation" | ICML | 2025 | `dblp:conf/icml/MaPF25` |
| AT19 | **prompt-injection** | Zhong et al., "Attention is All You Need to Defend Against Indirect Prompt Injection" | NDSS | 2026 | `dblp:conf/ndss/ZhongMCDCX26` |
| AT20 | **prompt-injection** | Jia et al., "The Task Shield: Enforcing Task Alignment Against Indirect Prompt Injection" | ACL | 2025 | `dblp:conf/acl/JiaWQS25` |

#### 多轮提示级攻击（prompt-level-multi-turn）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| AT21 | **decomposition-actorattack** | Du et al., "Multi-Turn Jailbreaking LLMs via Attention Shifting" | AAAI | 2025 | `dblp:conf/aaai/Du00GZ0S25` |
| AT22 | **decomposition-actorattack** | Chu et al., "JailbreakRadar: Comprehensive Assessment of Jailbreak Attacks" | ACL | 2025 | `dblp:conf/acl/ChuL000Z25` |
| AT23 | **gradual-escalation-crescendo** | Russinovich et al., "The Crescendo Multi-Turn LLM Jailbreak Attack" | USENIX | 2025 | `dblp:conf/uss/Russinovich0E25` |
| AT24 | **gradual-escalation-crescendo** | Hao et al., "CHASE: Contextual History for Adaptive and Simple Exploitation" | AAAI | 2026 | `dblp:conf/aaai/HaoLFCFWSYGLN26` |
| AT25 | **multi-agent-x-teaming** | Chen et al., "MetaCipher: Time-Persistent Universal Multi-Agent Cipher Jailbreak" | AAAI | 2026 | `dblp:conf/aaai/ChenSBGS26` |

#### 表示级攻击（representation-level）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| AT26 | **activation-engineering** | Zhang et al., "Differentiated Directional Intervention: Evading LLM Safety Alignment" | AAAI | 2026 | `dblp:conf/aaai/ZhangS26` |
| AT27 | **logit-steering** | Qi et al., "Safety Alignment Should be Made More Than Just a Few Tokens Deep" | ICLR | 2025 | `dblp:conf/iclr/QiPL0RBM025` |
| AT28 | **refusal-direction-ablation** | Arditi et al., "Refusal in Language Models Is Mediated by a Single Direction" | NeurIPS | 2024 | `dblp:conf/nips/ArditiOSPPGN24` |

*注：AT7（NeuroStrike）同时覆盖 neuron-suppression（神经元抑制），AT28（Arditi）同时覆盖 activation-engineering（激活工程）。*

---

### 2.3 防御策略（Defend）—— 22篇，11个叶子

#### 训练时防御（training-time）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| DF1 | **adversarial-training** | Sanyal et al., "AntiDote: Bi-level Adversarial Training for Tamper-Resistant LLMs" | AAAI | 2026 | `dblp:conf/aaai/SanyalRM26` |
| DF2 | **adversarial-training** | Xu et al., "When Human Preferences Flip: An Instance-Dependent Robust Loss for RLHF" | AAAI | 2026 | `dblp:conf/aaai/XuYCZ26` |
| DF3 | **circuit-breakers** | Zou et al., "Improving Alignment and Robustness with Circuit Breakers" | NeurIPS | 2024 | `dblp:conf/nips/ZouPWDLAKFH24` |
| DF4 | **circuit-breakers** | Farquhar et al., "MONA: Myopic Optimization with Non-myopic Approval" | ICML | 2025 | `dblp:conf/icml/FarquharVLEBGS25` |
| DF5 | **machine-unlearning** | Li et al., "Editing as Unlearning: Are Knowledge Editing Methods Strong Baselines?" | AAAI | 2026 | `dblp:conf/aaai/LiWSKQCWL26` |
| DF6 | **machine-unlearning** | Tian et al., "A Robust Unlearning Method with Adaptive Knowledge Guidance" | AAAI | 2026 | `dblp:conf/aaai/TianZ26` |
| DF7 | **safety-preserving-fine-tuning** | Yang et al., "AsFT: Anchoring Safety During LLM Fine-Tuning Within Narrow Safety Basin" | AAAI | 2026 | `dblp:conf/aaai/YangZLHJNYWDSY26` |
| DF8 | **safety-preserving-fine-tuning** | Bach et al., "Rethinking Deep Alignment Through the Lens of Incomplete Safety Learning" | AAAI | 2026 | `dblp:conf/aaai/BachNLT26` |
| DF9 | **tamper-resistant-training** | ⚠️ Tamirisa et al., "Tamper-Resistant Safeguards for Open-Weight LLMs" | ICLR | 2025 | `dblp:conf/iclr/TamirisaBPZGSLW25` |
| DF10 | **tamper-resistant-training** | Chen et al., "SDD: Self-Degraded Defense against Malicious Fine-tuning" | ACL | 2025 | `dblp:conf/acl/ChenLLZ25` |

#### 推理时防御（inference-time）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| DF11 | **activation-steering-defense** | Darabi et al., "EigenShield: Inference-Time, Model-Agnostic Jailbreaking Defense" | AAAI | 2026 | `dblp:conf/aaai/DarabiNTJKT26` |
| DF12 | **activation-steering-defense** | Obidov et al., "Dynamic Deep Prompt Optimization for Defending Against Jailbreak" | AAAI | 2026 | `dblp:conf/aaai/ObidovYGY26` |
| DF13 | **decoding-intervention** | Shang et al., "From Chaos to Cure: Prefix Heuristics Guided Model-Agnostic Detoxification" | AAAI | 2026 | `dblp:conf/aaai/ShangCRWLLZH26` |
| DF14 | **decoding-intervention** | Adak et al., "AURA: Affordance-Understanding and Risk-aware Alignment Technique" | AAAI | 2026 | `dblp:conf/aaai/AdakCBHAM26` |
| DF15 | **refining-based-aligner** | Rashid et al., "Chain-of-Thought Driven Adversarial Scenario Extrapolation" | AAAI | 2026 | `dblp:conf/aaai/RashidDWTM26` |
| DF16 | **refining-based-aligner** | Shen et al., "LLMdoctor: Token-Level Flow-Guided Preference Optimization" | AAAI | 2026 | `dblp:conf/aaai/ShenMWSZZC26` |

#### 守卫机制（guardrails）

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| DF17 | **pre-processing-input-filter** | Fang et al., "Disentangling Adversarial Prompts: A Semantic-Graph Defense" | AAAI | 2026 | `dblp:conf/aaai/FangF26` |
| DF18 | **pre-processing-input-filter** | Pu et al., "MirrorShield: Dynamic Adaptive Defense via Entropy-Guided Mirror Crafting" | AAAI | 2026 | `dblp:conf/aaai/PuLHZQZ26` |
| DF19 | **intra-processing-internal-monitor** | Goren et al., "AlignTree: Efficient Defense Against LLM Jailbreak Attacks" | AAAI | 2026 | `dblp:conf/aaai/GorenKW26` |
| DF20 | **intra-processing-internal-monitor** | Wang et al., "ConfGuard: A Simple and Effective Backdoor Detection for LLMs" | AAAI | 2026 | `dblp:conf/aaai/WangZLFJZX26` |
| DF21 | **post-processing-output-filter** | Zhao et al., "Value-Aligned Prompt Moderation via Zero-Shot Agentic Rewriting" | AAAI | 2026 | `dblp:conf/aaai/ZhaoCLLZG26` |
| DF22 | **post-processing-output-filter** | McKenzie et al., "STACK: Adversarial Attacks on LLM Safeguard Pipelines" | AAAI | 2026 | `dblp:conf/aaai/McKenzieHTDCTKG26` |

---

### 2.4 脆弱性机制（Understand）—— 16篇，10个叶子

| # | 叶子节点 | 选取论文 | 会议 | 年份 | DB ID |
|---|------|---------------|-------|------|-------|
| FM1 | **low-rank-safety-subspace** | Yang et al., "AsFT: Anchoring Safety During LLM Fine-Tuning Within Narrow Safety Basin" | AAAI | 2026 | `dblp:conf/aaai/YangZLHJNYWDSY26` |
| FM2 | **low-rank-safety-subspace** | Piras et al., "SOM Directions Are Better than One: Multi-Directional Refusal Suppression" | AAAI | 2026 | `dblp:conf/aaai/PirasMBORB26` |
| FM3 | **shallow-alignment** | Bach et al., "Rethinking Deep Alignment Through the Lens of Incomplete Safety Learning" | AAAI | 2026 | `dblp:conf/aaai/BachNLT26` |
| FM4 | **shallow-alignment** | Geng et al., "Control Illusion: The Failure of Instruction Hierarchies in LLMs" | AAAI | 2026 | `dblp:conf/aaai/GengLMHBAHF26` |
| FM5 | **sparse-safety-neurons** | Prakash et al., "Beyond I'm Sorry, I Can't: Dissecting Large-Language-Model Refusal" | AAAI | 2026 | `dblp:conf/aaai/PrakashYASCL26` |
| FM6 | **sparse-safety-neurons** | Le et al., "Unveiling AI Safety in Fine-tuning Quantized Model" | AAAI | 2026 | `dblp:conf/aaai/Le26` |
| FM7 | **alignment-tax** | Ali et al., "Operationalizing Pluralistic Values in LLM Alignment Reveals Trade-offs" | AAAI | 2026 | `dblp:conf/aaai/AliZKP26` |
| FM8 | **alignment-tax** | Chai et al., "Adaptive KL Control for Direct Preference Optimization" | AAAI | 2026 | `dblp:conf/aaai/Chai26` |
| FM9 | **gradient-conflict** | Bach et al., "Rethinking Deep Alignment Through the Lens of Incomplete Safety Learning" | AAAI | 2026 | `dblp:conf/aaai/BachNLT26` |
| FM10 | **gradient-conflict** | Chai et al., "Adaptive KL Control for DPO" | AAAI | 2026 | `dblp:conf/aaai/Chai26` |
| FM11 | **reward-hacking-overoptimization** | Kim et al., "Mitigating Length Bias in RLHF Through a Causal Lens" | AAAI | 2026 | `dblp:conf/aaai/KimOL26` |
| FM12 | **reward-hacking-overoptimization** | Ru et al., "RMO: Towards Better LLM Alignment via Reshaping Reward Margin Distributions" | AAAI | 2026 | `dblp:conf/aaai/RuHZ26` |
| FM13 | **alignment-forgetting** | Li et al., "LifeAlign: Lifelong Alignment for LLMs with Memory-Augmented Optimization" | AAAI | 2026 | `dblp:conf/aaai/LiZZYPCHLCH26` |
| FM14 | **alignment-forgetting** | Hahm et al., "Unintended Misalignment from Agentic Fine-Tuning: Risks and Mitigation" | AAAI | 2026 | `dblp:conf/aaai/HahmMJL26` |
| FM15 | **ood-failure-cross-lingual-modal** | Dutta et al., "ACID Test: A Benchmark for Cultural Safety and Alignment in LALMs" | AAAI | 2026 | `dblp:conf/aaai/DuttaJRVS26` |
| FM16 | **model-scale-dependence** | Bowen et al., "Scaling Trends for Data Poisoning in LLMs" | AAAI | 2025 | `dblp:conf/aaai/BowenMCKGP25` |

---

### 2.5 评估与基准（Measure）—— 12项评估资源

评估维度不选取论文复现，而是**采用**以下评估资源：

| 资源 | 类型 | 规模 | 用途 | 来源 |
|----------|------|------|---------|-----------|
| **JailbreakBench** | 数据集 | 100条有害指令 | 主要ASR度量 | Chao et al. 2024 |
| **JailbreakHub（IJP）** | 数据集 | 1,000条真实越狱提示 | 真实攻击评估 | Shen et al. CCS 2024 |
| **AdvBench** | 数据集 | 520条有害字符串 | 广度评估 | Zou et al. 2023 |
| **HarmBench** | 数据集 | 400条攻击（多类别） | 标准化评估 | Mazeika et al. 2024 |
| **OR-Bench** | 数据集 | 1,000条良性查询 | 过度拒绝/FPR | Cui et al. ICML 2025 |
| **AlpacaEval** | 数据集 | 805条正常指令 | 效用度量 | Li et al. 2023 |
| **MultiJail** | 数据集 | 315条多语言攻击 | 跨语言ASR | Deng et al. 2024 |
| **GPT-4o Judge** | 工具 | — | 1-5分有害性评分 | 参考论文方法 |
| **MMLU** | 基准 | 14,042道选择题 | 知识保留率 | Hendrycks et al. 2021 |
| **GSM8K** | 基准 | 1,319道数学题 | 推理保留率 | Cobbe et al. 2021 |
| **MT-Bench** | 基准 | 80个多轮问题 | 对话质量 | Zheng et al. 2023 |
| **RewardBench** | 基准 | 2,985个比较对 | 奖励模型评估 | Lambert et al. 2024 |

---

### 2.6 模型阵容（贯穿所有实验）

| 模型 | 规模 | 访问 | 角色 |
|-------|-------|--------|------|
| Llama-3-8B-Instruct | 8B | 开源 | **主力** — 社区标准 |
| Llama-3-8B（base） | 8B | 开源 | 对照组 — 度量对齐增益 |
| Llama-3.1-70B-Instruct | 70B | 开源 | 规模依赖性分析 |
| Vicuna-13B-v1.5 | 13B | 开源 | 较弱安全基线 |
| Mistral-7B-Instruct-v0.3 | 7B | 开源 | 替代架构家族 |
| Qwen2.5-7B-Instruct | 7B | 开源 | 非英语源模型 |
| GPT-4o-mini | — | API | 黑盒泛化测试 |

---

## 3. 实验设计：四阶段方案

### 阶段一：对齐构建基准（~1,000 GPU-小时）

**目标**: 系统性度量5种对齐范式下的内在安全率（ISR）和能力保留率。

| 实验 | 方法 | 基础模型 | 关键指标 | GPU估算 |
|-----------|--------|-----------|------------|----------|
| E1.1 | RLHF/PPO（AC1） | Llama-3-8B base | ISR + MMLU | 200h |
| E1.2 | DPO（AC3） | Llama-3-8B base | ISR + MMLU | 150h |
| E1.3 | Constitutional AI（AC17） | Llama-3-8B base | ISR + MMLU | 200h |
| E1.4 | RAIN Decoding（AC14） | Llama-3-8B-Instruct | ISR + 延迟 | 50h |
| E1.5 | Weak-to-Strong（AC12） | Llama-3-8B→70B | 安全泛化 | 200h |
| E1.6 | Multi-objective（AC5） | Llama-3-8B base | 安全-能力帕累托 | 100h |
| E1.7 | Poisoning robustness（AC9） | Llama-3-8B + RLHF | 脆弱性指数 | 100h |

### 阶段二：攻击评估（~1,500 GPU-小时）

**目标**: 在6个模型上评测14种代表性攻击的ASR。

**攻击×模型矩阵：**

| 攻击方法 | 类型 | 测试模型 | GPU估算 |
|--------------|------|--------------|----------|
| GCG（AT9） | 白盒优化 | 4个开源模型 | 150h |
| AutoDAN（基于AT9） | 隐蔽优化 | 4个开源模型 | 120h |
| PAIR（AT11） | 黑盒生成 | 全部6个 | 50h（API） |
| SEAS（AT12） | 自演进攻击 | 全部6个 | 80h |
| Harmful FT（AT1） | 权重修改 | Llama-3-8B | 100h |
| LoRA Backdoor（AT3） | PEFT攻击 | Llama-3-8B | 80h |
| Model Editing Attack（AT5） | 知识注入 | Llama-3-8B | 60h |
| JailbreakHub（AT13） | 手工模板 | 全部6个 | 30h |
| Many-shot（AT17） | 长上下文 | 全部6个 | 80h |
| Crescendo（AT23） | 多轮对话 | 全部6个 | 100h |
| MetaCipher（AT25） | 多智能体 | 全部6个 | 120h |
| Refusal Ablation（AT28） | 激活攻击 | 4个开源模型 | 80h |
| Differentiated Intervention（AT26） | 激活攻击 | 4个开源模型 | 80h |
| MultiJail（AT15） | 跨语言 | 全部6个 | 50h |

### 阶段三：防御评估（~2,000 GPU-小时）

**目标**: 交叉防御矩阵 —— 10种防御 × 6种攻击 × 4个模型。

| 防御方法 | 类别 | 防御对象 | GPU估算 |
|---------|----------|---------------|----------|
| TAR（DF9） | 训练时防篡改 | AT1, AT3（有害微调） | 200h |
| AntiDote（DF1） | 双层对抗训练 | AT1, AT3, AT5 | 200h |
| Circuit Breakers（DF3） | 训练时 | AT9-AT25（全部提示攻击） | 150h |
| AsFT（DF7） | 安全盆地锚定 | AT1（有害微调） | 150h |
| Machine Unlearning（DF5） | 知识移除 | AT1, AT5 | 150h |
| EigenShield（DF11） | 推理时激活防御 | 全部提示级攻击 | 100h |
| AlignTree（DF19） | 内处理监控 | 全部提示级攻击 | 100h |
| Semantic-Graph Guard（DF17） | 预处理过滤 | 全部提示级攻击 | 100h |
| MirrorShield（DF18） | 动态预处理 | 全部提示级攻击 | 100h |
| LLMdoctor（DF16） | 精炼对齐器 | 全部提示级攻击 | 120h |

**SEU画像**: 对每种通过8B测试的防御，分析额外延迟 + GPU内存开销 + OR-Bench上的FPR。

### 阶段四：交叉分析（~500 GPU-小时）

**7个核心研究问题：**

| RQ | 问题（中文） | 方法 |
|----|----------|--------|
| RQ1 | **对齐范式比较**: 哪种最安全？ | RLHF vs DPO vs CAI vs RAIN —— 相同基础、相同数据、相同评估 |
| RQ2 | **攻击迁移性**: GCG后缀是否跨模型迁移？ | Llama-3的GCG后缀 → Vicuna, Mistral, Qwen |
| RQ3 | **防御堆叠**: 训练+推理防御是叠加还是冗余？ | TAR（训练）+ EigenShield（推理） vs 各自单独使用 |
| RQ4 | **安全盆地假说**: 对齐方法影响后续鲁棒性吗？ | DPO对齐 vs RLHF对齐 → 有害微调 → 比较ASR |
| RQ5 | **安全的规模律**: 越大越安全吗？ | 7B → 8B → 13B → 70B 的ISR和ASR趋势 |
| RQ6 | **SEU帕累托前沿**: 什么是最优防御？ | 绘制全部防御的 FPR vs ΔASR, 延迟 vs ΔASR 帕累托图 |
| RQ7 | **跨模态泛化**: 文本攻击对VLM是否有效？ | 文本攻击 → LLaVA / GPT-4o vision 测试 |

---

## 4. 计算预算

| 阶段 | GPU-小时 | API费用 | 时间（8×A100） |
|-------|-----------|----------|-------------------|
| 阶段一：对齐构建 | ~1,000 | $200 | 5天 |
| 阶段二：攻击评估 | ~1,500 | $500 | 8天 |
| 阶段三：防御评估 | ~2,000 | $300 | 10天 |
| 阶段四：交叉分析 | ~500 | $200 | 3天 |
| GPT-4o评判 | — | $1,000-2,000 | 并行 |
| 余量（25%） | ~1,250 | $500 | 7天 |
| **总计** | **~6,250** | **~$3,200** | **33天** |

---

## 5. 分类覆盖率验证

```
对齐构建（ALIGNMENT CONSTRUCTION）   13/13 = 100% ✓
攻击方法（ATTACK METHODS）            17/17 = 100% ✓
防御策略（DEFENSE STRATEGIES）        11/11 = 100% ✓
脆弱性机制（FRAGILITY MECHANISMS）    10/10 = 100% ✓
─────────────────────────────────────────────
叶子节点覆盖总计                      51/51 = 100% ✓
选取论文总数                          92篇
DB中已有                              86/92（93.5%）
需补充                                6篇（GCG, PAIR, InstructGPT, CAI, Weak-to-Strong, TAR）
```

---

## 6. 缺失基础论文（优先补充清单）

| # | 论文 | 优先级 | 原因 |
|---|-------|----------|--------|
| 1 | **GCG（Zou et al. 2023）** | 🔴 关键 | 所有优化式攻击的基础；DB中75篇论文以此为基础 |
| 2 | **PAIR（Chao et al. 2023）** | 🔴 关键 | 37篇生成式攻击论文的参考基准 |
| 3 | **InstructGPT（Ouyang et al. 2022）** | 🔴 关键 | RLHF基础；DB中125篇RLHF/PPO论文 |
| 4 | **Constitutional AI（Bai et al. 2022）** | 🟡 高 | RLAIF基础；DB中12篇CAI论文 |
| 5 | **Weak-to-Strong（Burns et al. 2023）** | 🟡 高 | 可扩展监督基础；DB中12篇相关论文 |
| 6 | **Tamper-Resistant Safeguards（Tamirisa et al. 2025）** | 🟢 中 | DB中已有，需确认PDF可用 |

---

## 7. 后续步骤

1. **审核**: 将92篇论文选取方案提交领域专家审核；按需替换
2. **补充**: 将6篇缺失基础论文加入数据库
3. **确认**: 验证优先论文的代码/模型可用性
4. **搭建**: 统一评估工具链（vLLM + GPT-4o评判器 + SEU指标体系）
5. **执行**: 依次运行阶段一（对齐基准）→ 验证 → 阶段二至四
6. **撰写**: 将实验发现整合为SoK的实验评估章节

---

*研究Agent草案 v3 中文版。92篇论文 × 51个叶子节点 × 7维度分类体系。对标参考SEU论文的规模和实验方法。*
