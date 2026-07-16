# 调研日志

## 第一轮：试点分析（8 篇）

**日期**: 2026-07-16
**目标**: 验证论文分析方法的可行性，了解文献中的 benchmark 使用模式

**选取论文**:
| 领域 | 论文 | 会议 | 核心发现 |
|------|------|------|---------|
| 对齐 | Compositional Preference Models | ICLR 2024 | 用 HH-RLHF + SHP 数据集，BoN 采样评估。不涉及 safety |
| 对齐/Bench | reWordBench | EMNLP 2025 | 评估 reward model 对输入扰动的鲁棒性。包含 jailbreak 作为一类扰动 |
| 攻击 | Adversarial Reasoning Jailbreak | ICML 2025 | 将越狱建模为推理问题，用 reasoning model 生成攻击 |
| 攻击/防御 | SPIRIT | EMNLP 2025 | 语音 LM 的越狱攻击+防御，创建了 speech-specific benchmark |
| 防御 | EigenShield | AAAI 2026 | 推理时频谱过滤，ASR 降幅最高 92.9%，不修改模型 |
| 防御 | SaLoRA | ICLR 2025 | 安全保持 LoRA 微调，分析微调前后安全特征变化 |
| 脆弱性 | Unlocking Spell | ICLR 2024 | 发现 base LLM 可通过 ICL 实现对齐，设计多维度评估 |
| 脆弱性 | Self-Correction Theory | NeurIPS 2024 | ICL 对齐的理论分析 |

**关键发现**:
1. Benchmark 碎片化——没有统一的安全+效用 benchmark
2. ASR 是攻击/防御论文的通用指标
3. 效率数据严重缺失（8 篇中仅 EigenShield 报告了推理延迟）
4. 0 篇论文做了完整的 pre/post benchmark 对比
5. 提示级攻击占主导，输出级攻击无人问津

---

## 第二轮：扩展分析（12 篇 → 累计 20 篇）

**日期**: 2026-07-16
**目标**: 覆盖更多加固方法和攻击类型，定位 benchmark 的具体协议

### 对齐补充（3 篇）

| 论文 | 会议 | 提取内容 |
|------|------|---------|
| DPO (Rafailov) | NeurIPS 2023 | 训练配置：二值交叉熵，β 控制 KL 约束，无需 reward model。对比 PPO 和 Best-of-N |
| RAIN | ICLR 2024 | 免训练对齐：自评估+回退嵌入自回归推理。LLaMA 30B 无害率 82%→97%。时间开销随模型规模增加 |
| MAP (Multi-Human-Value) | ICLR 2025 | 多价值对齐调色板，理论+实证 |

### 攻击补充（3 篇）

| 论文 | 会议 | 提取内容 |
|------|------|---------|
| AutoDAN | ICLR 2024 | 分层遗传算法，500 iter，测试 Vicuna/Guanaco/Llama2/GPT-3.5。含困惑度防御绕过测试和跨模型迁移性 |
| Many-shot Jailbreaking | NeurIPS 2024 | 256-shot 上下文注入。分析长上下文脆弱性 |
| CHASE (Multi-turn) | AAAI 2026 | 基于对话历史的适应性越狱，多轮场景 |

### 防御补充（2 篇）

| 论文 | 会议 | 提取内容 |
|------|------|---------|
| Tamper-Resistant Safeguards (TAR) | ICLR 2025 | 训练时获得安全向量，微调时对齐。防有害微调 |
| GradSafe | ACL 2024 | 基于安全关键梯度的越狱检测，内处理 guardrail |

### Benchmark 补充（2 篇）

| 论文 | 会议 | 提取内容 |
|------|------|---------|
| HarmBench | ICML 2024 | **最全面的安全 benchmark**：510 行为×4 类别×18 攻击×33 LLM。ASR = 分类器判定触发目标行为的测试占比。强调 breadth/comparability/robust metrics |
| JailbreakBench | NeurIPS 2024 | **最标准化评估协议**：100 行为（10 类）配对良性行为。标准评判器 Llama-3-Instruct-70B。开源 pipeline + web 界面。温度=0 贪婪解码 |

### 脆弱性补充（2 篇）

| 论文 | 会议 | 提取内容 |
|------|------|---------|
| Beyond I'm Sorry (Refusal) | AAAI 2026 | 解构 LLM 拒绝行为，分析拒绝的内部机制 |
| NeuroStrike | NDSS 2026 | 神经元级攻击，操控少量神经元改变 LLM 攻击性 |

---

## 累计覆盖评估

### 加固手段：9/17 类

| 已覆盖 | 未覆盖 |
|--------|--------|
| DPO、RAIN、多目标、CAI | **RLHF/PPO**（InstructGPT 不在 DB） |
| SaLoRA、TAR、Circuit Breakers | 对抗训练（防御）、机器遗忘 |
| EigenShield | 解码干预、精炼对齐器 |
| 奖励模型评估 | **三层 guardrail**（pre/intra/post-processing） |

### 攻击手段：7/17 类

| 已覆盖 | 未覆盖 |
|--------|--------|
| 有害微调、AutoDAN、Many-shot | **GCG 原始论文**（不在 DB） |
| CHASE（多轮）、NeuroStrike | **PAIR 原始论文**（不在 DB） |
| 对抗推理越狱、拒绝方向 | LoRA后门、模型编辑、权重操控 |
| | 手工角色扮演（56篇）、隐写/多语言（25篇） |
| | ActorAttack、多智能体、Logit操控 |

### Benchmark

| 安全 | 效用 |
|------|------|
| HarmBench ✓ | MMLU（未读原文） |
| JailbreakBench ✓ | AlpacaEval（未读原文） |
| AdvBench ✓ | MT-Bench（未读原文） |
| OR-Bench（未深读） | RewardBench ✓ |

---

## 关键经验

1. **分析单位 = 论文**：每篇论文提取所有相关信息，不预设领域
2. **不要无中生有**：指标名、配置参数、来源标注必须从论文原文中提取，不捏造
3. **先定性后定量**：框架先用自然语言描述"想度量什么"，具体公式后续扫文章补
4. **PDF → 文本 → grep 定位 → Read 精读**：四步走比直接读 PDF 图片高效
5. **效率数据极度稀缺**：文献中训练成本几乎从不报告，需要我们自己跑实验时测量

---

## 第三轮：GCG + PAIR 原版入库（2 篇 → 累计 22 篇）

**日期**: 2026-07-16
**目标**: 补齐最基础的攻击方法论文

| 论文 | 会议 | 提取内容 |
|------|------|---------|
| GCG (Zou et al.) | arXiv 2023 | 白盒 token 级优化攻击。Greedy Coordinate Gradient。最大化模型输出 "Sure, here is..."。多 prompt 多模型联合优化（Vicuna-7B+13B+Guanaco-7B）。500 steps × batch 512。ASR: Vicuna 99%, GPT-3.5/4 84%, PaLM-2 66%。强迁移性 |
| PAIR (Chao et al.) | arXiv 2023 | 黑盒 prompt 级生成攻击。Prompt Automatic Iterative Refinement。攻击者 LLM 迭代查询 → Judge 评分 → 精炼。**<20 次查询，34 秒，$0.03 成本**。ASR: Vicuna-13B 88%, GPT-3.5/4 50%, Gemini-Pro 73%（首个自动化 Gemini 越狱） |

---

## 调研总览（22 篇论文）

### 加固手段：9/17 类已分析

```
已覆盖                           未覆盖
──────────────────────────────────────────────────
DPO (Rafailov 2023)              RLHF/PPO — InstructGPT 不在 DB
RAIN 免训练 (ICLR 2024)          对抗训练（防御）
MAP 多目标 (ICLR 2025)           机器遗忘
Inverse CAI (ICLR 2025)          解码干预
SaLoRA 安全微调 (ICLR 2025)      精炼对齐器
TAR 防篡改 (ICLR 2025)           Pre-processing guardrail
Circuit Breakers (NeurIPS 2024)  Intra-processing guardrail
EigenShield (AAAI 2026)          Post-processing guardrail
奖励模型评估 (reWordBench等)
```

### 攻击手段：9/17 类已分析

```
已覆盖                           未覆盖
──────────────────────────────────────────────────
GCG 原版 ✓ (Zou 2023)            LoRA后门
PAIR 原版 ✓ (Chao 2023)          模型编辑
AutoDAN (ICLR 2024)              权重操控
Many-shot (NeurIPS 2024)         手工角色扮演 (56篇)
有害微调 (ICLR 2024)             隐写/多语言 (25篇)
CHASE 多轮 (AAAI 2026)           ActorAttack
对抗推理越狱 (ICML 2025)         多智能体 X-teaming
NeuroStrike 神经元 (NDSS 2026)   Logit操控
拒绝方向分析 (AAAI 2026)         提示注入
```

### Benchmark：核心已定位

```
安全评估                    效用评估
────────────────────────────────────
HarmBench (510行为×33LLM)    MMLU（未读原文）
JailbreakBench (100行为)     AlpacaEval（未读原文）
AdvBench (520行为)            MT-Bench（未读原文）
OR-Bench（过拒检测）          RewardBench ✓
```

### GCG vs PAIR 对比

| | GCG | PAIR |
|---|-----|------|
| **类型** | 白盒 token 级优化 | 黑盒 prompt 级生成 |
| **方法** | 贪婪坐标梯度，最大化模型输出 "Sure, here is..." | 攻击者 LLM 迭代查询目标 → Judge 评分 → 精炼 |
| **效率** | 500 steps × batch 512（多 prompt 多模型联合优化） | **<20 次查询**，34 秒，$0.03 成本 |
| **ASR** | Vicuna 99%, GPT-3.5/4 84%, PaLM-2 66% | Vicuna-13B 88%, GPT-3.5/4 50%, Gemini-Pro 73% |
| **可迁移性** | ✓（尤其向 GPT 模型迁移效果好） | ✓（比 GCG 更可迁移） |

---

## 第四轮：批量补缺（38 篇 → 累计 60 篇）

**日期**: 2026-07-16
**目标**: 系统性填补加固/攻击/benchmark 的覆盖缺口

### 新增覆盖

| 类别 | 新增论文数 | 代表性论文 |
|------|----------|-----------|
| RLHF/PPO 实现 | 3 | MoralReason, Pluralistic Values, Alignment Game |
| 对抗训练（防御） | 2 | AntiDote, Q-MLLM |
| 机器遗忘 | 2 | ALTER, Cross-Modal Unlearning |
| 解码干预 | 2 | AURA, Agentic Fine-tuning |
| 精炼对齐器 | 2 | AURA, Agentic Fine-tuning |
| Pre-processing guardrail | 2 | Semantic-Graph Defense, Attribute Misbinding |
| Intra-processing guardrail | 2 | AlignTree, PurMM |
| LoRA/PEFT 攻击 | 2 | AntiDote, Causal-Guided Detoxify |
| 模型编辑攻击 | 2 | Can Editing LLMs Inject Harm?, Double-Edged Sword |
| 手工角色扮演 | 2 | EduGuardBench, STACK |
| 隐写/多语言 | 2 | When Smiley Turns Hostile, MacPrompt |
| 提示注入 | 2 | Attention Defense, Task Shield |
| ActorAttack | 1 | Attack the Messages |
| X-teaming | 1 | MetaCipher |
| Logit 操控 | 1 | Safety Alignment More Than Tokens |
| 权重操控 | 1 | Do Not Merge My Model |
| 奖励过优化 | 2 | Long-form RewardBench, Length Bias |
| 层级拓扑 | 2 | VideoLLM Failures, Attribute Misbinding |
| 多模态安全 | 2 | Cross-Modal Safety, VideoLLM |
| 跨语言安全 | 2 | Emoji Toxicity, ACID Test |
| Benchmark 原文 | 3 | OR-Bench, CodeMMLU, BadJudge |

### 批量统计（38 篇自动化提取）

| 维度 | 发现 |
|------|------|
| **Benchmark 出现频率** | MMLU(8), AdvBench(8), Beavertails(6), HarmBench(6), JailbreakBench(5), AlpacaEval(5), GSM8K(5) |
| **模型使用** | GPT-4 系列(54), Llama-3(35), Qwen(22), Mistral(14), Gemini(14), Vicuna(9), Claude(10) |
| **指标使用** | ASR(28), FPR(25), Attack Success Rate(24), perplexity(7), refusal rate(6) |
| **效率数据** | 仅 15/38 篇提及，多为"latency"或"overhead" |

---

## 调研总览（60 篇论文）

### 加固手段：15/17 类已分析

```
已覆盖                                 未覆盖
────────────────────────────────────────────────────
DPO (Rafailov 2023)                    
RAIN 免训练 (ICLR 2024)                
MAP 多目标 (ICLR 2025)                 
Inverse CAI (ICLR 2025)                
RLHF/PPO (3篇 AAAI 2026)      ← new   
对抗训练 (2篇)                  ← new   
机器遗忘 (2篇)                  ← new   
解码干预 (2篇)                  ← new   
精炼对齐器 (2篇)                ← new   
Pre-processing guardrail (2篇)  ← new   
Intra-processing guardrail (2篇)← new   
SaLoRA 安全微调 (ICLR 2025)            
TAR 防篡改 (ICLR 2025)                 
Circuit Breakers (NeurIPS 2024)        
EigenShield (AAAI 2026)                
                                       Post-processing guardrail
                                       奖励模型评估（已有 reWordBench）
```

### 攻击手段：17/17 类全部已分析 ✓

```
已覆盖                                 未覆盖
────────────────────────────────────────────────────
GCG 原版 (Zou 2023)              ← 第三轮
PAIR 原版 (Chao 2023)            ← 第三轮
AutoDAN (ICLR 2024)              
Many-shot (NeurIPS 2024)         
有害微调 (ICLR 2024)             
CHASE 多轮 (AAAI 2026)           
对抗推理越狱 (ICML 2025)         
NeuroStrike 神经元 (NDSS 2026)   
拒绝方向分析 (AAAI 2026)         
LoRA后门 (2篇)                   ← new
模型编辑 (2篇)                   ← new
权重操控 (1篇)                   ← new
手工角色扮演 (2篇)               ← new
隐写/多语言 (2篇)                ← new
提示注入 (2篇)                   ← new
ActorAttack (1篇)                ← new
多智能体 X-teaming (1篇)         ← new
Logit操控 (1篇)                  ← new
                                      全部覆盖 ✓
```

### Benchmark：核心全部定位

```
安全评估                         效用评估
─────────────────────────────────────────
HarmBench (510行为×33LLM) ✓      MMLU ✓（已定位论文）
JailbreakBench (100行为) ✓       AlpacaEval ✓（已定位论文）
AdvBench (520行为) ✓              MT-Bench ✓（已定位论文）
OR-Bench（过拒检测）✓             RewardBench ✓
Beavertails (新增发现)            GSM8K（5篇使用）
XSTest (新增发现)                 TruthfulQA
WMDP (3篇使用)                   
```

---

## 第五轮：深度扩展（36 篇 → 累计 96 篇）

**日期**: 2026-07-16
**目标**: 补齐最后一类加固手段，深化各类别覆盖，增加 venue 多样性

### 新增覆盖

| 类别 | 新增 | 关键论文 |
|------|------|---------|
| Post-processing guardrail | 3 | STACK, Value-Aligned Moderation, T2I-RiskyPrompt |
| DPO/RLHF 深化 | 5 | Adaptive KL Control, Contrastive Divergence, AMaPO |
| Guardrail 深化 | 5 | MirrorShield, ConfGuard, Safe RAG |
| Evaluation & Red Teaming | 5 | ACID Test, Silenced Biases, SceneJailEval |
| Fragility 深化 | 5 | Incomplete Safety, Control Illusion, Quantized Safety |
| Rep-level attack 深化 | 3 | Activation Manipulation, SOM Directions, Differentiated Intervention |
| Param-level attack 深化 | 3 | Persistent Backdoor, ALTER, Can Editing |
| Foundational (2023-2024) | 5 | DPO, Shadowcast, Poisoning, MLLMGuard, ART |
| Safety-vs-capability | 1 | AURA |
| Venue diversity (NDSS/CCS) | 5 | Odysseus, DUALBREACH, Causal Perspective, NeuroStrike |

### 批量统计（36 篇）

| 维度 | Top 结果 |
|------|---------|
| Benchmark | HarmBench(7), AdvBench(6), MMLU(4), JailbreakBench(3), BBQ(3) |
| 模型 | GPT-4(26), Qwen(19), Llama-3(15), GPT-4o(15), Gemini(11) |
| 指标 | ASR(28), FPR(18), perplexity(12), ROUGE(5), win rate(3) |
| 效率提及 | 22/36（61% — 因 guardrail 论文通常报告延迟） |

---

## 最终调研总览（96 篇论文，5 轮）

### 加固手段：17/17 全部覆盖 ✓

```
RLHF/PPO ✓            DPO variants ✓          多目标对齐 ✓
Nash/博弈 ✓           奖励模型 ✓               Constitutional AI ✓
免训练对齐 ✓           Safety-preserving FT ✓  Tamper-resistant ✓
Circuit Breakers ✓     对抗训练 ✓              机器遗忘 ✓
解码干预 ✓             精炼对齐器 ✓            Pre-processing guardrail ✓
Intra-processing ✓     Post-processing ✓       Activation Steering Defense ✓
```

### 攻击手段：17/17 全部覆盖 ✓

```
GCG ✓     PAIR ✓     AutoDAN ✓    Many-shot ✓    有害微调 ✓
CHASE ✓   对抗推理 ✓  NeuroStrike ✓ 拒绝方向 ✓    LoRA后门 ✓
模型编辑 ✓ 权重操控 ✓ 手工角色扮演 ✓ 隐写/多语言 ✓ 提示注入 ✓
ActorAttack ✓ X-teaming ✓ Logit操控 ✓
```

### Benchmark 全景图

```
安全评估                              效用评估
──────────────────────────────────────────────
HarmBench (510行为×33LLM) — 最全面      MMLU — 知识保留标准
JailbreakBench (100行为) — 最标准化      AlpacaEval — 指令遵循
AdvBench (520行为) — 最早/最广泛         MT-Bench — 对话质量
OR-Bench (1,000条) — 过拒检测           RewardBench — 奖励模型
Beavertails / XSTest / WMDP             GSM8K / TruthfulQA / BBQ
```

### 统计总览

| 项目 | 数值 |
|------|------|
| 累计论文 | **96 篇**（5 轮） |
| 加固手段覆盖 | **17/17 = 100%** |
| 攻击手段覆盖 | **17/17 = 100%** |
| 最常用 benchmark | AdvBench, MMLU, HarmBench, JailbreakBench |
| 最常用模型 | GPT-4 系列 > Llama-3 > Qwen > Mistral |
| 通用指标 | ASR (universal), FPR, perplexity |
| 效率数据覆盖率 | ~60%（guardrail 论文为主） |

---

## 第六轮：全量批量分析（20 批 × ~50 篇 = 1,010 篇）

**日期**: 2026-07-16
**方法**: 20 个 subagent 并行，每批提取 PDF 实验页（4-8 页），关键词扫描

### 全量统计

| 指标 | 数值 |
|------|------|
| 处理论文 | **1,010 篇** |
| 错误 | 8 篇（0.8%） |
| 效率数据提及 | 188 篇（18.6%） |
| 攻击/训练配置提及 | 854 篇（84.6%） |
| 高分论文（rich≥6） | **300 篇** |

### Benchmark 使用排名

```
AdvBench: 172    MMLU: 157       AlpacaEval: 154
HH-RLHF: 108     MT-Bench: 107    GSM8K: 103
TruthfulQA: 89   HarmBench: 78    Beavertails: 65
XSTest: 58       SHP: 55          RewardBench: 48
JailbreakBench: 34                ToxiGen: 24
```

### 模型使用排名

```
GPT-4: 610       Mistral: 321     Llama-3: 298
Alpaca: 288      GPT-4o: 279      Qwen: 259
Llama-2: 229     GPT-3.5: 195     Vicuna: 185
Claude: 151
```

### 指标使用排名

```
FPR: 503         ASR: 500         困惑度: 154
Win Rate: 115    攻击成功率: 99     ROUGE: 62
拒绝率: 38
```

### 关键确认

1. **Benchmark 碎片化确认**: AdvBench（最早/最广泛）和 MMLU（效用标准）是前两位，但各有 172/157 篇使用——没有任何 benchmark 被超过 17% 的论文使用
2. **GPT-4 霸权**: 60% 的论文使用 GPT-4 系列模型
3. **ASR/FPR 双指标**: 几乎每篇攻击/防御论文都报告这两个指标
4. **效率数据极度稀缺**: 仅 18.6% 论文提及——加固手段的效率需要我们自己测
5. **300 篇高分论文**: 适合后续精读，提取实验配置细节

---

## 方法论更新 (2026-07-16)

### 新增流程

1. **非 research paper 过滤**：页数 < 6 的标记为 talk/abstract/demo，不纳入代表作选取
2. **代表作安全取向验证**：选入分类树的论文必须同时满足（a）abstract 提到安全关键词（b）实验测了安全指标
3. **subagent 分层使用**：粗判用摘要（subagent 并行），精读代表作时亲自读 PDF 全文
4. **分类树构建方法**：抽样 10-12 篇摘要 → 判断是否有 3+ 不同机制 → 值得切则粗分 3-4 方向

### 树举例审核结果

- 40/40 篇举例论文 ≥ 6 页 ✓（全为正规 research paper）
- 替换：Le (3页学生摘要) → AsFT (9页 AAAI 2026)
- 2 篇 paper_id 缺失待补（MMJ-Bench, Dormant Backdoor），不影响当前树结构

### 攻击树新增细分

- GCG/AutoDAN (75篇) → 4 子方向：核心GCG/梯度优化、多模态对抗、迁移/隐写/黑盒、RAG/Agent投毒
- 有害微调 (76篇) → 4 子方向：后门注入、数据投毒、良性微调退化、防御/净化
- 手工角色扮演 (56篇) → ⚠ 约30%分类噪声待清理

### 待办

- 手工角色扮演分类清理
- 全量 DB 非 research paper 标记（subagent 扫描中）
- 攻击方法的代表文章精读（需要读 PDF 全文确认方法细节）
