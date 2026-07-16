# SoK Experimental Evaluation Plan: LLM Safety Alignment

> **Survey**: "LLM Safety Alignment: Build, Break & Defend — A Systematization of Knowledge"
> **Status**: DRAFT v3 — Multi-Dimensional Taxonomy + Full Lifecycle Evaluation
> **Date**: 2026-07-15
> **Reference**: Modeled after *"Guardrails in the Crosshairs: A Systematic Evaluation of Safeguards Against LLM Jailbreak Attacks"* (SEU Framework, 6-dimension guardrail taxonomy)
> **DB**: 1,196 core papers, 91.6% PDF coverage, 51 taxonomy leaves across 6 trees

---

## 0. Taxonomy Overview: Multi-Dimensional Classification System

Inspired by the reference paper's 6-dimensional guardrail taxonomy, we redesigned our SoK's classification to capture the full alignment lifecycle. Each paper is tagged across **7 orthogonal dimensions**, enabling cross-dimensional analysis impossible with a single tree.

### Dimension Map

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                         MULTI-DIMENSIONAL TAXONOMY (7 DIMENSIONS)                        │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│  DIMENSION 1: LIFECYCLE PHASE (primary axis)                                            │
│  ├── Build: Alignment Construction                                                      │
│  ├── Break: Attack Methods                                                              │
│  ├── Defend: Defense Strategies                                                         │
│  ├── Understand: Fragility Mechanisms                                                   │
│  └── Measure: Evaluation & Benchmarks                                                   │
│                                                                                          │
│  DIMENSION 2: TECHNICAL PARADIGM                                                        │
│  ├── For Alignment: RL-based / Direct-Preference / Game-Theoretic / Training-Free /     │
│  │                  Constitutional / Data-Centric                                        │
│  ├── For Attacks:   Optimization / Generation / Manual / Implicit / Weight-Modification │
│  │                  / Activation-Manipulation                                           │
│  └── For Defenses:  Rule-based / Model-based (ML/Statistical) / LLM-based               │
│                                                                                          │
│  DIMENSION 3: ALIGNMENT INTERVENTION LEVEL (where alignment is built & broken)          │
│  ├── Weight-level: RLHF/DPO training, harmful FT, LoRA backdoors, model merging        │
│  ├── Representation-level: Activation steering, refusal ablation, neuron manipulation  │
│  ├── Prompt-level: System instructions, GCG suffixes, role-play jailbreaks             │
│  └── Output-level: Decoding intervention, logit steering, output refinement             │
│                                                                                          │
│  DIMENSION 4: ACCESS REQUIREMENT (Applicability)                                        │
│  ├── White-box: Requires model weights / gradients / internal states                   │
│  ├── Gray-box: Requires output logits / token probabilities                            │
│  └── Black-box: Requires only API access / text output                                 │
│                                                                                          │
│  DIMENSION 5: DEPLOYMENT STAGE (Intervention Timing)                                    │
│  ├── Pre-deployment: Training-time, data curation, architecture design                  │
│  ├── At-inference:  Pre-processing, intra-processing (forward pass)                    │
│  └── Post-response: Post-processing, output filtering                                  │
│                                                                                          │
│  DIMENSION 6: GRANULARITY                                                               │
│  ├── Token-level: Individual tokens, attention heads                                   │
│  ├── Sequence-level: Full prompt/response pairs                                        │
│  ├── Session-level: Multi-turn conversations                                           │
│  └── Model-level: Architecture, training regime, scale                                 │
│                                                                                          │
│  DIMENSION 7: MODALITY SCOPE                                                            │
│  ├── Text-only: Pure language models                                                   │
│  ├── Vision-Language: Image + text inputs                                              │
│  └── Multimodal: Audio, video, code, structured data                                   │
│                                                                                          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

> **💡 Key insight (Dimension 3)**: Alignment is NOT a one-time training fix. Construction and breaking coexist at all four levels (Weight / Representation / Prompt / Output) — a multi-layer arms race. Even RLHF-aligned weights remain vulnerable at the representation, prompt, and output levels. **This is the core question our SoK asks: just how fragile is post-training safety alignment?**

### How This Compares to the Reference Paper

| Reference Paper (Guardrails Only) | Our SoK (Full Lifecycle) |
|---|---|
| **D1**: Intervention Stages (Pre/Intra/Post) | → Expanded to include Training-time + Decoding-time (5 stages) |
| **D2**: Technical Paradigms (Rule/ML/LLM-based) | → Extended to cover Alignment + Attack paradigms too |
| **D3**: Safety Granularity (Token/Seq/Session) | → Added Model-level for architecture analysis |
| **D4**: Reactiveness (Static/Dynamic) | → Merged into Deployment Stage + Paradigm |
| **D5**: Applicability (White/Black-box) | → Added Gray-box for logit-level access |
| **D6**: Explainability (Opaque/Explainable) | → Tagged per paper as cross-cutting attribute |
| *Not in reference* | **D7**: Modality Scope (Text/VLM/Multimodal) |

### Paper Distribution Across Dimensions

| Domain | Core Papers | % of Total |
|--------|------------|------------|
| Alignment Construction | 507 | 42.4% |
| Prompt-Level Attack | 218 | 18.2% |
| Evaluation & Red Teaming | 141 | 11.8% |
| Robust Training Defenses | 84 | 7.0% |
| Mechanisms of Fragility | 83 | 6.9% |
| Parameter-Level Attack | 64 | 5.4% |
| Runtime Guardrails | 54 | 4.5% |
| Representation-Level Attack | 45 | 3.8% |
| **TOTAL** | **1,196** | **100%** |

---

## 1. Evaluation Framework

> ⚠️ This section is a heuristic draft. Specific metric definitions will be filled in after systematic literature review.

Our SoK's core question is **"just how fragile is safety alignment?"**. The evaluation framework is built around this: using a unified benchmark, measure the safety and utility of hardened models (alignment methods, defense methods) before and after applying various attacks, while also recording the efficiency cost of both hardening and attacking.

### 1.1 Framework Pipeline

```
Step 0: Apply hardening ────── Measure Efficiency
    │                        (training GPU-hours, data volume, inference latency, memory)
    ▼
Step 1: Benchmark baseline ─── Measure Safety + Utility
    │                        (performance of the hardened model before attack)
    ▼
Step 2: Apply attack ───────── Measure attack Efficiency
    │                        (queries, iterations, samples needed, access level)
    ▼
Step 3: Benchmark remeasure ── Measure Safety + Utility delta
                             (post-attack vs. baseline = fragility)
```

### 1.1.1 Survey Overview

Based on systematic analysis of **1,106 papers** (96 deep-read + 1,010 keyword-scanned across 20 parallel subagents):

**Benchmark Usage Rankings**

```
Safety Benchmarks                      Utility Benchmarks
────────────────────────────────────────────────────────
AdvBench       172 papers (17.0%)      MMLU            157 papers (15.5%)
HarmBench       78 papers (7.7%)       AlpacaEval      154 papers (15.2%)
Beavertails     65 papers (6.4%)       HH-RLHF         108 papers (10.7%)
XSTest          58 papers (5.7%)       MT-Bench        107 papers (10.6%)
JailbreakBench  34 papers (3.4%)       GSM8K           103 papers (10.2%)
ToxiGen         24 papers (2.4%)       TruthfulQA       89 papers (8.8%)
WildGuard       20 papers (2.0%)       RewardBench      48 papers (4.8%)
```

**Model Usage Rankings**

```
GPT-4      610 (60%)   Mistral    321 (32%)   Llama-3    298 (30%)
GPT-4o     279 (28%)   Qwen       259 (26%)   Llama-2    229 (23%)
GPT-3.5    195 (19%)   Vicuna     185 (18%)   Claude     151 (15%)
```

**Metric Usage Rankings**

```
ASR         500 (50%)    FPR         503 (50%)
Perplexity  154 (15%)    Win Rate    115 (11%)
Attack SR    99 (10%)    Refusal Rate 38 (4%)
```

**Efficiency data**: only 18.6% of papers mention it. **300 rich papers** flagged for deep reading.

**Deep-read coverage**: Hardening methods 24/24 categories ✓, Attack methods 17/17 categories ✓. Full survey log at `devdocs/research-methodology/`.

### 1.1.2 Refined Classification

Based on 96 deep-read papers, "hardening" is re-split into **Alignment Construction** (Build) and **Safety Hardening** (Harden), forming a three-layer system with attacks.

#### Alignment Construction (Build)

> Large categories (RLHF, DPO, Safety FT) are decomposed to level 3 with optimization targets and safety-relevant representatives.

```
Preference Optimization (344 DB papers)
  RLHF/PPO (134) — reward model + PPO
    ├── Policy Optimization
    │   PPO unstable, safety signal weak → improve loss/optimization
    │   · WALKSAFE: semantic graph + random walk risk scoring, Bi-GRPO replaces PPO
    │   · SDGO: LLM serves as both discriminator & generator, closing safety gap
    ├── Reward/Data
    │   Preference data lacks safety annotation; single-turn training fails multi-turn
    │   · PKU-SafeRLHF: safety-specific dataset, separate helpfulness & harmlessness labels
    │   · MTSA: multi-turn red-teaming generates adversarial samples for robust training
    ├── Theory
    │   Why does RLHF work/fail? When does alignment collapse?
    │   · Jailbreaking as Reward Misspecification (ICLR 2025): jailbreaks exploit uncovered reward regions
    │   · Unified Analysis (ICML 2025): theoretical bounds for noisy labels in RLHF/DPO
    └── Domain-specific
        Does RLHF still work for new architectures/modalities?
        · dLLM safety: first safety alignment study for diffusion language models
  DPO variants (190) — no reward model, learn directly from preferences
    ├── Multi-objective Safety
    │   DPO optimizes a single dimension; safety+helpfulness can't both win
    │   · SPA: enforces trustworthy-before-helpful ordering, safety-constrained optimization
    │   · Sequential PO: decomposes multi-dimensional preferences into sequential optimization
    ├── Robust DPO
    │   Preference labels are noisy, flip, or get poisoned → training is corrupted
    │   · Preference Flip: instance-dependent robust loss, downweights suspect labels
    │   · AutoMixAlign: adaptive mixing of helpful+harmless+honest data ratios
    └── DPO for Defense
        Can preference optimization itself defend against attacks?
        · SecAlign (CCS 2025): DPO-trained task alignment resists indirect prompt injection
        · MPO (ACL 2025): multilingual safety via reward gap optimization
  Multi-objective (35) — optimize safety+helpfulness+others jointly
    ├── Pareto frontier (8)  find optimal trade-off between objectives → ParetoHqD, Robust MO-DPO
    ├── Pluralistic values (23) handle diverse/cross-cultural value conflicts → Pluralistic Values, FGD-Align
    └── Sequential decomp (5) decompose multi-dim into sequential steps → Sequential PO, Magic-Token
  Nash game-theoretic (10) — alignment as equilibrium

Training-free (99)
  Decoding-time (73) — intervene at inference, no weight modification
    ├── Contrastive Decoding
    │   Run "safe path" and "unsafe path" simultaneously, use logit difference to steer
    │   · ACD (AAAI 2026): adversarial contrastive decoding, optimize safe/adversarial soft prompts
    │   · DeAL (ACL 2025): embed alignment objective directly into decoding process
    ├── Test-time Optimization
    │   Lightweight online optimizer adjusts output distribution, like micro-DPO without weight updates
    │   · LLMdoctor (AAAI 2026): token-level flow-guided preference optimization at test time
    │   · Nudging (ACL 2025): guided decoding pushes base model output toward aligned direction
    ├── Representation Intervention
    │   Directly manipulate internal activations to steer harmful representations toward safety
    │   · SCANS (AAAI 2025): safety-conscious activation steering, mitigates over-refusal
    │   · Multi-Attribute Steering (ACL 2025): controllable multi-attribute intervention
    └── Prefix/Distribution Guidance
        Modify prompt prefixes or directly adjust logit distributions to constrain safety
        · Prefix Detoxification (AAAI 2026): adaptive prefix heuristic guided detoxification
        · SDA (AAAI 2026): steering-driven distribution alignment, multi-domain without weight change
  Prompt steering (26) — system prompt constraints

Rule-based (26)
  Constitutional AI (12) — AI feedback instead of human
  Principle-driven (14) — explicit value encoding

Data-centric (143)
  Preference curation (105) — data quality → safety quality
    ├── Quality filtering   select "good" preference pairs → length bias fix, RewardBench, Pareto data
    ├── Conflict/denoise    handle annotation conflicts & flipped labels → conflict-aware, flip detection
    └── Diversity/coverage  data representing diverse human values → cultural safety, pluralistic values
  Synthetic generation (68) — AI-generated preferences
    ├── Self-play/evolution  model generates → evaluates → iterates on own data → Beyond Human Data, SMPRO
    ├── AI annotation        use another LLM to score/rank preferences → Generative Reward Modeling
    └── Data augmentation    derive more samples from existing preferences → HumorReject
  Weak-to-Strong (13) — weak supervision → strong model
```

```
Preference Optimization (344 DB papers)
  RLHF/PPO            134 — reward model + PPO
  DPO variants         190 — no reward model needed
  Multi-objective       35 — safety+helpfulness jointly
  Nash game-theoretic   10 — alignment as equilibrium

Training-free (99)
  Decoding-time         73 — RAIN, self-eval + rewind
  Prompt steering        26 — system prompt constraints

Rule-based (26)
  Constitutional AI     12 — AI feedback instead of human
  Principle-driven      14 — explicit value encoding

Data-centric (143)
  Preference curation  105 — data quality → safety quality
  Synthetic generation   68 — AI-generated preferences
  Poisoning robustness    7 — anti-poisoning
  Weak-to-Strong        13 — weak supervision → strong model
```

#### Safety Hardening (Harden)

```
Training-time (233)
  Safety-preserving FT (134) — keep safety during downstream FT
    ├── Degradation Mech    Incomplete Safety Learning (diagnosis: safety features naturally shallow, FT erases them first)
    │                       Quantized Model Safety (4-bit QLoRA significantly degrades safety)
    ├── Novel Paradigms     HumorReject (humor replaces refusal prefixes)
    │                       Magic-Token (switchable safety control at inference)
    └── Small/Efficient     EASE (practical safety for small LMs)
                            STAR-1 (1K data for reasoning LM safety)
  Adversarial training (43) — inject adversarial samples, but threat models differ
    ├── Anti harmful FT     attacker modifies weights → AntiDote (bi-level), Vulnerability-Aware
    ├── Anti jailbreak      attacker crafts malicious prompts → AGD (game defense), Refusal Feature AT
    ├── Anti backdoor       attacker implants hidden triggers → BEEAR (embedding-based removal)
    ├── Anti relearning     attacker recovers erased knowledge → Robust Unlearning (sharpness-aware)
    └── Multimodal/data     specialized scenarios → Q-MLLM (VLM), Data to Defense, Contrastive Repr
  Tamper-resistant (14) — specifically against harmful FT / model merging
    ├── Immunization       make weights "immune" to harmful FT → TAR, Vaccine, Model Immunization
    ├── Adversarial FT     inject adversarial samples during training → AntiDote, Booster
    └── Anti-merge/self    prevent model merging attacks or self-degraded defense → Do Not Merge, SDD
  Circuit Breakers        3 — representation rerouting
  Machine unlearning (39) — selectively erase harmful knowledge; differs in "how" and "what"
    ├── Method            how to erase efficiently → ALTER (asymmetric LoRA), RMU (representation misdirection), Precise Erasure
    ├── Robustness        can erased knowledge be recovered → Adversarial Unlearning, SEUF (MoE unlearning)
    ├── Safety-specific   what to erase → Constrained Knowledge Unlearning, Revoke Backdoors
    └── Cross-modal       different modalities/languages → Cross-Modal Unlearning (MLLM), Multilingual Unlearning

Inference-time (141)
  Activation steering (63) — manipulate internal activations, no weight change
    ├── Spectral/subspace    locate harmful "channels" via random matrix theory → EigenShield (ASR↓92.9%)
    │                        Bleeding Pathways (hidden state discriminability analysis)
    ├── Safety direction     find "safety direction" in activation space, project onto it → SCANS
    │                        SDA (steering-driven distribution alignment, multi-domain)
    ├── Multi-layer tree     hierarchical safety classifier, layer-by-layer jailbreak detection → AlignTree
    └── Dynamic adapt        adjust steering strategy on-the-fly → Dynamic Prompt Opt, SafeInfer
  Decoding intervention (52) — modify decoding strategy, no external model
    ├── Contrastive decoding  run safe/unsafe paths simultaneously, steer by logit difference
    │                        · ACD, Contrastive Decoding for Code
    ├── Distribution/prefix   adjust output logit distribution or inject safety prefix → Prefix Detox, LLMdoctor
    ├── Risk-aware decoding   dynamically assess risk at each decoding step → AURA
    └── Domain-specific       safety decoding for specific domains → agent safety, reasoning (STaR)
  Refining aligner (26) — lightweight extra model corrects main model output
    ├── Output correction     train small aligner to fix unsafe outputs → AURA, CoT Extrapolation
    ├── Test-time alignment   lightweight online preference optimization, micro-DPO → LLMdoctor, Stream Aligner
    ├── Safety reminder       inject safety signals during generation to wake model awareness
    │                        · SafetyReminder (VLM), Path Drift (reasoning models)
    └── Attack-as-defense     leverage attack techniques for defense → Attack Techniques for Defense

Guardrail (119)
  Pre-processing (53) — intercept before model input
    ├── Classifier-based   binary harmful/safe classifier → Llama Guard, WildGuard, Prompt Guard
    ├── Semantic/graph      parse input semantics to find hidden attacks → Semantic-Graph Defense
    ├── Statistical/entropy detect anomalies via statistical features → MirrorShield, Perplexity Filter
    └── Domain-specific     RAG/VLM/identity protection → ShieldRAG, DAVSP
  Intra-processing (38) — analyze internal states during forward pass
    ├── Gradient analysis   analyze gradient signals → GradSafe
    ├── Attention/represent  monitor attention heads & representations → AlignTree, ConfGuard
    └── Domain-specific     architecture/scenario-specific → PurMM (MLLM), Attention Defense
  Post-processing (28) — intercept after model output
    ├── LLM judge           use another LLM to judge output safety → Llama Guard, WildGuard
    ├── Perturbation/consistency  perturb output, check consistency → SmoothLLM, SemanticSmooth
    └── Domain-specific     modality/scenario-specific → T2I-RiskyPrompt, MMJ-Bench
```

#### Attack Methods (Break)

```
Prompt-level single-turn (200)
  Optimization GCG/AutoDAN (75) — white-box token optimization
    ├── Core GCG/gradient (~25)   GCG variants, coordinate ascent, AutoDAN
    ├── Multimodal (~17)          GCG extended to VLM/audio/medical MLLM → StyleBreak, MMJ-Bench
    ├── Transfer/stealth (~12)    cross-model transfer, universal suffix, black-box proxy
    └── RAG/Agent poisoning (~10) GCG against retrieval/agent systems → Joint-GCG, DUALBREACH
  Generation PAIR (37) — black-box LLM generation, no gradient needed
  Manual role-play (56) — persona/cognitive bias/template exploits
    ⚠ ~30% classification noise (some are defenses/benchmarks, not role-play), pending cleanup
  Cipher/multilingual (25) — steganography, emoji, low-resource
  Many-shot (3) — long-context injection
  Prompt injection (4) — indirect injection

Prompt-level multi-turn (52)
  Crescendo (27) — gradual escalation
  ActorAttack (12) — task decomposition
  X-teaming (13) — strongest attack, ASR>90%

Parameter-level (57)
  Harmful fine-tuning (76) — safety attacks during fine-tuning
    ├── Backdoor injection (~30)   implant triggers during FT → Persistent Backdoor, Dormant Backdoor
    ├── Data poisoning (~20)       corrupt RLHF/DPO preference data → Cost-Minimized, Scaling Trends
    ├── Benign FT degradation (~15) no attacker, normal FT erodes safety → Agentic FT Misalignment
    └── Defense/purge (~10)        safety protection during FT → PurMM, Attention Realignment
  LoRA backdoor (6) — PEFT injection
  Model editing (13) — knowledge editing attack
  Weight manipulation (15) — model merging attack

Representation-level (38)
  Activation manip (14)
  Refusal ablation (7) — refusal mediated by single direction
  Logit steering          6
  Neuron suppression      3
```

#### Key Findings

1. **Prompt-level attacks are saturated**: GCG and PAIR are universal baselines
2. **Parameter-level attacks underestimated**: Harmful FT achieves 91.8% ASR
3. **Multi-turn is the frontier**: X-teaming achieves ASR>90% against existing defenses
4. **Output-level attacks nearly absent**: only 6 logit steering papers
5. **No perfect defense**: EigenShield's 92.9% ASR reduction is best, still 7% leak
6. **Efficiency-safety tradeoff**: inference-time defenses are practical but add latency; training-time defenses are thorough but costly

### 1.2 Four Measurement Stages

**Step 0 — Efficiency of Hardening**

How expensive is it to deploy alignment or defense? Cost differences across hardening paradigms are a key comparison dimension for the SoK.

| Hardening type | What we want to measure (qualitative) |
|---------------|--------------------------------------|
| Training-time alignment (RLHF, DPO, CAI) | Training GPU-hours, preference data volume |
| Training-time defense (TAR, Circuit Breakers) | Additional training cost, invasiveness to original training pipeline |
| Inference-time defense (EigenShield, AlignTree) | Extra latency, GPU memory overhead |
| Training-free alignment (RAIN, Prompt Steering) | Decoding/prompt-level cost |

**Step 1 — Safety + Utility Baseline**

How does the hardened model perform before any attack? This is the baseline for later comparison, and also enables cross-hardening comparison.

| Dimension | What we want to measure (qualitative) |
|-----------|--------------------------------------|
| **Safety** | Against a standardized set of harmful inputs, what proportion does the model refuse/comply with? Higher = stronger hardening |
| **Utility** | Performance on standard capability benchmarks (knowledge, reasoning, conversation); any over-refusal — benign requests misclassified as harmful? |

**Step 2 — Efficiency of Attacks**

The cost-effectiveness of an attack directly determines its practical threat. Qi et al.'s finding was shocking precisely because "$0.20 + 5 gradient steps" could dismantle alignment.

| Dimension | What we want to measure (qualitative) |
|-----------|--------------------------------------|
| **Cost** | How many queries, training samples, optimization iterations, GPU-hours needed? |
| **Access level** | White-box (needs weights/gradients), gray-box (needs logits), or black-box (API only)? |

**Step 3 — Safety + Utility Delta After Attack**

The core fragility measurement. The same benchmark run before and after attack — the delta is how much of the hardening was "broken."

| Dimension | What we want to measure (qualitative) |
|-----------|--------------------------------------|
| **Safety drop** | How much safety degraded after attack? Total collapse or partial? Differences across hardening methods against the same attack? |
| **Utility change** | Did the attack also degrade general capability? Some attacks (e.g., harmful fine-tuning) may damage utility along with safety |
| **Failure pattern** | Global collapse or localized vulnerability? Does the model fail on all harm categories or only certain ones? |

### 1.3 Three Classes of Test Subjects

The framework applies uniformly to three classes — only the Step 0 "hardening" differs:

| Subject | Step 0 hardening | Core question |
|---------|-----------------|---------------|
| **Alignment methods** | RLHF / DPO / CAI / RAIN etc. | How do different alignment paradigms compare in attack resilience? |
| **Defense methods** | TAR / Circuit Breakers / EigenShield etc. | Can defenses effectively resist their targeted attack surface? |
| **Base model (baseline)** | None | How dangerous is an unaligned model? (reference baseline) |

### 1.4 Attack Surface Coverage

Different attack levels reveal where alignment is most fragile:

| Attack level | Representative methods | Framework compatibility |
|-------------|----------------------|------------------------|
| **Weight-level** | Harmful fine-tuning, LoRA backdoors, model editing | Attack changes model itself; Step 1 = original, Step 3 = fine-tuned model |
| **Prompt-level** | GCG, PAIR, Crescendo, Many-shot | Injected at inference; Step 1 without, Step 3 with attack |
| **Representation-level** | Refusal direction ablation, activation manipulation | Injected at inference; compatible with framework; white-box attacks may not work on black-box benchmark subsets |
| **Output-level** | Logit steering, forced decoding | Injected at inference; compatible with framework |

### 1.5 Cases Incompatible with the Unified Benchmark

Some attacks may not fit neatly into the pre/post benchmark comparison:

| Case | Example | Alternative |
|------|---------|-------------|
| Multi-turn attacks | Crescendo — single-turn benchmark prompts cannot capture gradual escalation | Use dedicated multi-turn evaluation sets (e.g., SafeMTData), keeping the pre/post structure |
| Cross-lingual/cross-modal attacks | Steganography jailbreaks, multilingual attacks | Extend benchmark with corresponding modality/language test cases |
| Attack IS the training process | Harmful fine-tuning changes model weights | Pre/post still valid — "post" simply measures the fine-tuned model rather than inference-time injection |

### 1.6 Pilot Paper Analysis (20 Papers)

To ground the framework in existing literature, we analyzed 20 representative papers (6 alignment, 6 attack, 4 defense, 4 benchmark), extracting benchmark protocols, attack hyperparameters, and hardening implementation details.

**Benchmark Landscape**:

| Finding | Detail |
|---------|--------|
| **HarmBench is the most comprehensive safety benchmark** | 510 behaviors × 4 functional categories × 18 attacks × 33 LLMs. ASR = % of test cases where target behavior is elicited |
| **JailbreakBench has the most standardized evaluation protocol** | 100 behaviors (10 categories aligned with OpenAI usage policy), paired benign behaviors for over-refusal detection. Standard judge: Llama-3-Instruct-70B |
| **No benchmark covers safety + utility together** | Papers combine datasets ad-hoc: HarmBench/JailbreakBench/AdvBench for safety, MMLU/MT-Bench/AlpacaEval for utility |
| **Protocol consensus** | Greedy decoding (T=0), GPT-4 or Llama-3 as judge, ASR as primary safety metric |

**Attack Configurations (ready to reuse)**:

| Attack | Source | Key Config |
|--------|--------|------------|
| GCG | Zou et al. (2023), baseline in 12/20 papers | 500 iter, batch 512, greedy decoding |
| AutoDAN | Liu et al. (ICLR 2024) | Hierarchical GA, 500 iter, 4 open-source models + GPT-3.5 |
| Many-shot | Anil et al. (NeurIPS 2024) | 256-shot in-context injection |
| Harmful FT | Qi et al. (ICLR 2024) | 10/50/100 shot, 5 epochs, lr=5e-5, batch=10 |
| PAIR | Chao et al. (2023) | ~20 queries/attempt, black-box, attacker=Mixtral-8×7B |

**Hardening Implementation Details**:

| Method | Paper | Key Config |
|--------|-------|------------|
| DPO | Rafailov et al. (NeurIPS 2023) | Binary cross-entropy, β controls KL constraint, simpler than PPO |
| RAIN | Li et al. (ICLR 2024) | Training-free: self-evaluation + rewind in auto-regressive inference |
| Circuit Breakers | Zou et al. (NeurIPS 2024) | Representation rerouting loss + retain loss |
| TAR | Tamirisa et al. (ICLR 2025) | Safety vector obtained at training, fine-tuning aligned to it |
| EigenShield | Darabi et al. (AAAI 2026) | Inference-time spectral filtering, no retraining needed |

**What Makes Our Framework Unique**:

| Already in literature | NOT in literature (= our contribution) |
|----------------------|----------------------------------------|
| ASR comparison across attacks (HarmBench) | Resilience comparison across alignment methods (RLHF vs DPO vs CAI under same attacks) |
| ASR reduction across defenses (JailbreakBench) | Full pre/post pipeline: harden → benchmark → attack → remeasure |
| Safety + utility evaluated separately (all papers) | Tracking BOTH safety and utility pre/post attack under unified benchmark |
| Inference latency for defenses (EigenShield et al.) | Standardized training-time efficiency measurement (nearly absent in literature) |

---

## 2. Paper Selection: Complete Leaf-by-Leaf Coverage

### Selection Methodology
1. **Coverage-first**: ≥1 paper per leaf node (51 leaves)
2. **Quality filter**: Top venues preferred (ICLR/NeurIPS/ICML/ACL/CCS/USENIX/AAAI/NDSS)
3. **Recency**: 2024-2026 preferred (2023 only for foundational papers)
4. **Diversity**: Mix of method types (Attack/Defense/Analysis/Benchmark)
5. **Reproducibility**: Open-weight models preferred; public code noted

### Total: 92 papers selected across 51 leaves + cross-cutting coverage

---

### 2.1 ALIGNMENT CONSTRUCTION (Build) — 20 papers, 13 leaves

#### preference-optimization (507 domain papers)

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| AC1 | **rlhf-ppo** | ⚠️ Ouyang et al., "Training Language Models to Follow Instructions with Human Feedback" (InstructGPT) | NeurIPS | 2022 | *ex-DB* |
| AC2 | **rlhf-ppo** | An et al., "MoralReason: Generalizable Moral Decision Alignment via Reasoning-Level RL" | AAAI | 2026 | `dblp:conf/aaai/AnD26` |
| AC3 | **dpo-variants** | Rafailov et al., "Direct Preference Optimization" | NeurIPS | 2023 | `dblp:conf/nips/RafailovSMMEF23` |
| AC4 | **dpo-variants** | Chen et al., "Preference Optimization via Contrastive Divergence" | AAAI | 2026 | `dblp:conf/aaai/ChenLZWLQG26` |
| AC5 | **multi-objective** | Gu et al., "ParetoHqD: Fast Offline Multiobjective Alignment" | AAAI | 2026 | `dblp:conf/aaai/GuWMZJ26` |
| AC6 | **nash-game-theoretic** | Choi et al., "Self-Improving Robust Preference Optimization" | ICLR | 2025 | `dblp:conf/iclr/ChoiAGPA25` |
| AC7 | **reward-modeling** | Huang et al., "Long-form RewardBench: Evaluating Reward Models for Long-form Generation" | AAAI | 2026 | `dblp:conf/aaai/HuangHLYLCXZCZ26` |

#### data-centric

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| AC8 | **preference-data-curation** | Bhattacharyya et al., "ALPHA: Action-Based Learning for Pluralistic Human Alignment" | AAAI | 2026 | `dblp:conf/aaai/BhattacharyyaAS26` |
| AC9 | **preference-poisoning-robustness** | Fu et al., "PoisonBench: Assessing LLM Vulnerability to Poisoned Preference Data" | ICML | 2025 | `dblp:conf/icml/FuS0C0B25` |
| AC10 | **preference-poisoning-robustness** | Wang et al., "RLHFPoison: Reward Poisoning Attack for RLHF" | ACL | 2024 | `dblp:conf/acl/Wang0CVX24` |
| AC11 | **synthetic-preference-generation** | Huang et al., "SPA: Achieving Consensus via Self-Priority Optimization" | AAAI | 2026 | `dblp:conf/aaai/HuangWZ26` |
| AC12 | **weak-to-strong-scalable-oversight** | ⚠️ Burns et al., "Weak-to-Strong Generalization" (OpenAI) | arXiv | 2023 | *ex-DB* |
| AC13 | **weak-to-strong-scalable-oversight** | Lang et al., "Selective Weak-to-Strong Generalization" | AAAI | 2026 | `dblp:conf/aaai/LangHL26` |

#### training-free

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| AC14 | **decoding-time-alignment** | Li et al., "RAIN: Your Language Models Can Align Themselves without Finetuning" | ICLR | 2024 | `dblp:conf/iclr/LiWZ0024` |
| AC15 | **decoding-time-alignment** | Shang et al., "From Chaos to Cure: A Prefix Heuristics Guided Detoxification" | AAAI | 2026 | `dblp:conf/aaai/ShangCRWLLZH26` |
| AC16 | **prompt-based-steering** | Mahmud et al., "Inference-Aware Prompt Optimization for Aligning Black-Box LLMs" | AAAI | 2026 | `dblp:conf/aaai/MahmudNWZ26` |

#### constitutional-rule-based

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| AC17 | **constitutional-ai** | ⚠️ Bai et al., "Constitutional AI: Harmlessness from AI Feedback" | arXiv | 2022 | *ex-DB* |
| AC18 | **constitutional-ai** | Wang et al., "STAR-1: Safer Alignment of Reasoning LLMs with 1K Data" | AAAI | 2026 | `dblp:conf/aaai/WangTWWLMBKX26` |
| AC19 | **principle-driven-alignment** | Xu et al., "Towards Better Value Principles for LLM Alignment: A Systematic Evaluation" | ACL | 2025 | `dblp:conf/acl/XuYYMX025` |
| AC20 | **principle-driven-alignment** | Ye et al., "Generative Psycho-Lexical Approach for Constructing Value Systems in LLMs" | ACL | 2025 | `dblp:conf/acl/YeZXZRZS25` |

---

### 2.2 ATTACK METHODS (Break) — 28 papers, 17 leaves

#### parameter-level

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| AT1 | **harmful-fine-tuning** | Qi et al., "Fine-tuning Aligned Language Models Compromises Safety" | ICLR | 2024 | `dblp:conf/iclr/Qi0XC0M024` |
| AT2 | **harmful-fine-tuning** | Cui et al., "Persistent Backdoor Attacks Under Continual Fine-Tuning of LLMs" | AAAI | 2026 | `dblp:conf/aaai/CuiHJZ26` |
| AT3 | **lora-peft-attack** | Chen et al., "Causal-Guided Detoxify Backdoor Attack of Open-Weight LoRA Models" | NDSS | 2026 | `dblp:conf/ndss/ChenSWC26` |
| AT4 | **lora-peft-attack** | Liu et al., "ELBA-Bench: An Efficient Learning Backdoor Attacks Benchmark for LLMs" | ACL | 2025 | `dblp:conf/acl/LiuLH0LCHT25` |
| AT5 | **model-editing** | Chen et al., "Can Editing LLMs Inject Harm?" | AAAI | 2026 | `dblp:conf/aaai/ChenHLCLXGGYXYW26` |
| AT6 | **model-editing** | Huang et al., "Model Editing as a Double-Edged Sword" | AAAI | 2026 | `dblp:conf/aaai/HuangTWLLPLCS26` |
| AT7 | **weight-manipulation** | Wu et al., "NeuroStrike: Neuron-Level Attacks on Aligned LLMs" | NDSS | 2026 | `dblp:conf/ndss/WuBRTPS26` |
| AT8 | **weight-manipulation** | Li et al., "Do Not Merge My Model! Safeguarding Against Unauthorized Model Merging" | AAAI | 2026 | `dblp:conf/aaai/LiPCTSSPZ26` |

#### prompt-level-single-turn

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| AT9 | **optimization-gcg-autodan** | ⚠️ Zou et al., "Universal and Transferable Adversarial Attacks" (GCG) | arXiv | 2023 | *ex-DB* |
| AT10 | **optimization-gcg-autodan** | Yang et al., "CoSPED: Consistent Soft Prompt Targeted Data Extraction and Defense" | AAAI | 2026 | `dblp:conf/aaai/YangFT26` |
| AT11 | **generation-pair-advprompter** | ⚠️ Chao et al., "Jailbreaking Black Box LLMs in Twenty Queries" (PAIR) | arXiv | 2023 | *ex-DB* |
| AT12 | **generation-pair-advprompter** | Diao et al., "SEAS: Self-Evolving Adversarial Safety Optimization for LLMs" | AAAI | 2025 | `dblp:conf/aaai/DiaoLLLWCX25` |
| AT13 | **manual-role-play** | Shen et al., "Do Anything Now: Characterizing In-The-Wild Jailbreak Prompts" (JailbreakHub) | CCS | 2024 | `dblp:conf/ccs/ShenC0SZ24` |
| AT14 | **manual-role-play** | Yang et al., "Exploiting Synergistic Cognitive Biases to Bypass Safety in LLMs" | AAAI | 2026 | `dblp:conf/aaai/YangZTHH26` |
| AT15 | **implicit-cipher-multilingual** | Li et al., "Odysseus: Jailbreaking Commercial Multimodal LLM via Dual Steganography" | NDSS | 2026 | `dblp:conf/ndss/LiCLJT26` |
| AT16 | **implicit-cipher-multilingual** | Cui et al., "When Smiley Turns Hostile: Interpreting How Emojis Trigger LLM Toxicity" | AAAI | 2026 | `dblp:conf/aaai/CuiFWYZSWQH26` |
| AT17 | **many-shot-jailbreaking** | Anil et al., "Many-shot Jailbreaking" | NeurIPS | 2024 | `dblp:conf/nips/AnilDPSBKBTMFMA24` |
| AT18 | **many-shot-jailbreaking** | Ma et al., "PANDAS: Improving Many-shot Jailbreaking via Positive Affirmation" | ICML | 2025 | `dblp:conf/icml/MaPF25` |
| AT19 | **prompt-injection** | Zhong et al., "Attention is All You Need to Defend Against Indirect Prompt Injection" | NDSS | 2026 | `dblp:conf/ndss/ZhongMCDCX26` |
| AT20 | **prompt-injection** | Jia et al., "The Task Shield: Enforcing Task Alignment Against Indirect Prompt Injection" | ACL | 2025 | `dblp:conf/acl/JiaWQS25` |

#### prompt-level-multi-turn

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| AT21 | **decomposition-actorattack** | Du et al., "Multi-Turn Jailbreaking LLMs via Attention Shifting" | AAAI | 2025 | `dblp:conf/aaai/Du00GZ0S25` |
| AT22 | **decomposition-actorattack** | Chu et al., "JailbreakRadar: Comprehensive Assessment of Jailbreak Attacks" | ACL | 2025 | `dblp:conf/acl/ChuL000Z25` |
| AT23 | **gradual-escalation-crescendo** | Russinovich et al., "The Crescendo Multi-Turn LLM Jailbreak Attack" | USENIX | 2025 | `dblp:conf/uss/Russinovich0E25` |
| AT24 | **gradual-escalation-crescendo** | Hao et al., "CHASE: Contextual History for Adaptive and Simple Exploitation" | AAAI | 2026 | `dblp:conf/aaai/HaoLFCFWSYGLN26` |
| AT25 | **multi-agent-x-teaming** | Chen et al., "MetaCipher: Time-Persistent Universal Multi-Agent Cipher Jailbreak" | AAAI | 2026 | `dblp:conf/aaai/ChenSBGS26` |

#### representation-level

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| AT26 | **activation-engineering** | Zhang et al., "Differentiated Directional Intervention: Evading LLM Safety Alignment" | AAAI | 2026 | `dblp:conf/aaai/ZhangS26` |
| AT27 | **logit-steering** | Qi et al., "Safety Alignment Should be Made More Than Just a Few Tokens Deep" | ICLR | 2025 | `dblp:conf/iclr/QiPL0RBM025` |
| AT28 | **refusal-direction-ablation** | Arditi et al., "Refusal in Language Models Is Mediated by a Single Direction" | NeurIPS | 2024 | `dblp:conf/nips/ArditiOSPPGN24` |

*Note: AT7 (NeuroStrike) also covers neuron-suppression, and AT28 (Arditi) also covers activation-engineering.*

---

### 2.3 DEFENSE STRATEGIES (Defend) — 22 papers, 11 leaves

#### training-time

| # | Leaf | Selected Paper | Venue | Year | DB ID |
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

#### inference-time

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| DF11 | **activation-steering-defense** | Darabi et al., "EigenShield: Inference-Time, Model-Agnostic Jailbreaking Defense" | AAAI | 2026 | `dblp:conf/aaai/DarabiNTJKT26` |
| DF12 | **activation-steering-defense** | Obidov et al., "Dynamic Deep Prompt Optimization for Defending Against Jailbreak" | AAAI | 2026 | `dblp:conf/aaai/ObidovYGY26` |
| DF13 | **decoding-intervention** | Shang et al., "From Chaos to Cure: Prefix Heuristics Guided Model-Agnostic Detoxification" | AAAI | 2026 | `dblp:conf/aaai/ShangCRWLLZH26` |
| DF14 | **decoding-intervention** | Adak et al., "AURA: Affordance-Understanding and Risk-aware Alignment Technique" | AAAI | 2026 | `dblp:conf/aaai/AdakCBHAM26` |
| DF15 | **refining-based-aligner** | Rashid et al., "Chain-of-Thought Driven Adversarial Scenario Extrapolation" | AAAI | 2026 | `dblp:conf/aaai/RashidDWTM26` |
| DF16 | **refining-based-aligner** | Shen et al., "LLMdoctor: Token-Level Flow-Guided Preference Optimization" | AAAI | 2026 | `dblp:conf/aaai/ShenMWSZZC26` |

#### guardrails

| # | Leaf | Selected Paper | Venue | Year | DB ID |
|---|------|---------------|-------|------|-------|
| DF17 | **pre-processing-input-filter** | Fang et al., "Disentangling Adversarial Prompts: A Semantic-Graph Defense" | AAAI | 2026 | `dblp:conf/aaai/FangF26` |
| DF18 | **pre-processing-input-filter** | Pu et al., "MirrorShield: Dynamic Adaptive Defense via Entropy-Guided Mirror Crafting" | AAAI | 2026 | `dblp:conf/aaai/PuLHZQZ26` |
| DF19 | **intra-processing-internal-monitor** | Goren et al., "AlignTree: Efficient Defense Against LLM Jailbreak Attacks" | AAAI | 2026 | `dblp:conf/aaai/GorenKW26` |
| DF20 | **intra-processing-internal-monitor** | Wang et al., "ConfGuard: A Simple and Effective Backdoor Detection for LLMs" | AAAI | 2026 | `dblp:conf/aaai/WangZLFJZX26` |
| DF21 | **post-processing-output-filter** | Zhao et al., "Value-Aligned Prompt Moderation via Zero-Shot Agentic Rewriting" | AAAI | 2026 | `dblp:conf/aaai/ZhaoCLLZG26` |
| DF22 | **post-processing-output-filter** | McKenzie et al., "STACK: Adversarial Attacks on LLM Safeguard Pipelines" | AAAI | 2026 | `dblp:conf/aaai/McKenzieHTDCTKG26` |

---

### 2.4 FRAGILITY MECHANISMS (Understand) — 16 papers, 10 leaves

| # | Leaf | Selected Paper | Venue | Year | DB ID |
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

### 2.5 EVALUATION & BENCHMARKS (Measure) — 6 papers + 7 datasets

Rather than selecting papers to reproduce, we **adopt** these evaluation resources:

| Resource | Type | Size | Purpose | Reference |
|----------|------|------|---------|-----------|
| **JailbreakBench** | Dataset | 100 harmful instructions | Primary ASR measurement | Chao et al. 2024 |
| **JailbreakHub (IJP)** | Dataset | 1,000 wild jailbreak prompts | Real-world attack eval | Shen et al. CCS 2024 |
| **AdvBench** | Dataset | 520 harmful strings | Breadth evaluation | Zou et al. 2023 |
| **HarmBench** | Dataset | 400 attacks | Standardized eval | Mazeika et al. 2024 |
| **OR-Bench** | Dataset | 1,000 benign queries | Over-refusal / FPR | Cui et al. ICML 2025 |
| **AlpacaEval** | Dataset | 805 normal instructs | Utility measurement | Li et al. 2023 |
| **MultiJail** | Dataset | 315 multilingual | Cross-lingual ASR | Deng et al. 2024 |
| **GPT-4o Judge** | Tool | — | 1-5 harmfulness scoring | Ref paper methodology |
| **MMLU** | Benchmark | 14,042 MCQs | Knowledge retention | Hendrycks et al. 2021 |
| **GSM8K** | Benchmark | 1,319 math problems | Reasoning retention | Cobbe et al. 2021 |
| **MT-Bench** | Benchmark | 80 multi-turn | Conversation quality | Zheng et al. 2023 |
| **RewardBench** | Benchmark | 2,985 comparisons | Reward model eval | Lambert et al. 2024 |

---

### 2.6 MODEL LINEUP (cross-cutting across all experiments)

| Model | Scale | Access | Role |
|-------|-------|--------|------|
| Llama-3-8B-Instruct | 8B | Open | **Primary** — community standard |
| Llama-3-8B (base) | 8B | Open | Control — alignment gain measurement |
| Llama-3.1-70B-Instruct | 70B | Open | Scale dependence analysis |
| Vicuna-13B-v1.5 | 13B | Open | Weaker safety baseline |
| Mistral-7B-Instruct-v0.3 | 7B | Open | Alternative architecture |
| Qwen2.5-7B-Instruct | 7B | Open | Non-English-origin model |
| GPT-4o-mini | — | API | Black-box generalization |

---

## 3. Experimental Design: 4-Phase Plan

### Phase 1: Alignment Construction Benchmark (~1,000 GPU-hours)

**Goal**: Systematically measure ISR and capability retention across 5 alignment paradigms.

| Experiment | Method | Base Model | Key Metric | GPU Est. |
|-----------|--------|-----------|------------|----------|
| E1.1 | RLHF/PPO (AC1) | Llama-3-8B base | ISR + MMLU | 200h |
| E1.2 | DPO (AC3) | Llama-3-8B base | ISR + MMLU | 150h |
| E1.3 | Constitutional AI (AC17) | Llama-3-8B base | ISR + MMLU | 200h |
| E1.4 | RAIN Decoding (AC14) | Llama-3-8B-Instruct | ISR + Latency | 50h |
| E1.5 | Weak-to-Strong (AC12) | Llama-3-8B→70B | Safety generalization | 200h |
| E1.6 | Multi-objective (AC5) | Llama-3-8B base | Safety-capability Pareto | 100h |
| E1.7 | Poisoning robustness (AC9) | Llama-3-8B + RLHF | Vulnerability Index | 100h |

### Phase 2: Attack Evaluation (~1,500 GPU-hours)

**Goal**: Benchmark ASR of 12 representative attacks across 6 models.

**Attack × Model Matrix:**

| Attack Method | Type | Models Tested | GPU Est. |
|--------------|------|--------------|----------|
| GCG (AT9) | White-box optimization | 4 open-weight | 150h |
| AutoDAN (AT9-related) | Stealth optimization | 4 open-weight | 120h |
| PAIR (AT11) | Black-box generation | All 6 | 50h (API) |
| SEAS (AT12) | Self-evolving attack | All 6 | 80h |
| Harmful FT (AT1) | Weight modification | Llama-3-8B | 100h |
| LoRA Backdoor (AT3) | PEFT attack | Llama-3-8B | 80h |
| Model Editing Attack (AT5) | Knowledge injection | Llama-3-8B | 60h |
| JailbreakHub (AT13) | Manual template | All 6 | 30h |
| Many-shot (AT17) | Long-context | All 6 | 80h |
| Crescendo (AT23) | Multi-turn | All 6 | 100h |
| MetaCipher (AT25) | Multi-agent | All 6 | 120h |
| Refusal Ablation (AT28) | Activation attack | 4 open-weight | 80h |
| Differentiated Intervention (AT26) | Activation attack | 4 open-weight | 80h |
| MultiJail (AT15) | Cross-lingual | All 6 | 50h |

### Phase 3: Defense Evaluation (~2,000 GPU-hours)

**Goal**: Cross-defense matrix — 10 defenses × 6 attacks × 4 models.

| Defense | Category | Tested Against | GPU Est. |
|---------|----------|---------------|----------|
| TAR (DF9) | Training-time tamper-resistance | AT1, AT3 (harmful FT) | 200h |
| AntiDote (DF1) | Bi-level adv training | AT1, AT3, AT5 | 200h |
| Circuit Breakers (DF3) | Training-time | AT9-AT25 (all prompt) | 150h |
| AsFT (DF7) | Safety basin anchoring | AT1 (harmful FT) | 150h |
| Machine Unlearning (DF5) | Knowledge removal | AT1, AT5 | 150h |
| EigenShield (DF11) | Inference-time activation | All prompt-level | 100h |
| AlignTree (DF19) | Intra-processing | All prompt-level | 100h |
| Semantic-Graph Guard (DF17) | Pre-processing | All prompt-level | 100h |
| MirrorShield (DF18) | Dynamic pre-processing | All prompt-level | 100h |
| LLMdoctor (DF16) | Refining aligner | All prompt-level | 120h |

**SEU profiling**: For each defense that passes the 8B test, profile Extra Delay + GPU Overhead + FPR on OR-Bench.

### Phase 4: Cross-Analysis (~500 GPU-hours)

**7 Key Research Questions:**

| RQ | Question | Method |
|----|----------|--------|
| RQ1 | **Alignment paradigm comparison**: Which is safest? | RLHF vs DPO vs CAI vs RAIN — same base, same data, same eval |
| RQ2 | **Attack transferability**: Do suffixes transfer? | GCG suffix from Llama-3 → Vicuna, Mistral, Qwen |
| RQ3 | **Defense stacking**: Additive or redundant? | TAR (training) + EigenShield (inference) vs each alone |
| RQ4 | **Safety basin hypothesis**: Does alignment method affect robustness? | DPO-aligned vs RLHF-aligned → harmful FT → ASR |
| RQ5 | **Scale law of safety**: Better with size? | 7B → 8B → 13B → 70B ISR and ASR trends |
| RQ6 | **SEU Pareto frontier**: Optimal defense? | Plot FPR vs ΔASR, Latency vs ΔASR for all defenses |
| RQ7 | **Cross-modal generalization**: Text attacks on VLMs? | Test text-only attacks against LLaVA / GPT-4o vision |

---

## 4. Compute Budget

| Phase | GPU-Hours | API Cost | Timeline (8×A100) |
|-------|-----------|----------|-------------------|
| Phase 1: Alignment | ~1,000 | $200 | 5 days |
| Phase 2: Attacks | ~1,500 | $500 | 8 days |
| Phase 3: Defenses | ~2,000 | $300 | 10 days |
| Phase 4: Cross-Analysis | ~500 | $200 | 3 days |
| GPT-4o Judging | — | $1,000-2,000 | Parallel |
| Contingency (25%) | ~1,250 | $500 | 7 days |
| **TOTAL** | **~6,250** | **~$3,200** | **33 days** |

---

## 5. Taxonomy Coverage Verification

```
ALIGNMENT CONSTRUCTION  13/13 = 100% ✓
ATTACK METHODS          17/17 = 100% ✓
DEFENSE STRATEGIES      11/11 = 100% ✓
FRAGILITY MECHANISMS    10/10 = 100% ✓
─────────────────────────────────────
TOTAL LEAVES COVERED    51/51 = 100% ✓
TOTAL PAPERS SELECTED   92 papers
PAPERS IN DB            86/92 (93.5%)
PAPERS NEED ADDITION     6 papers (GCG, PAIR, InstructGPT, CAI, Weak-to-Strong, TAR)
```

---

## 6. Missing Foundational Papers (Priority Action Items)

| # | Paper | Priority | Reason |
|---|-------|----------|--------|
| 1 | **GCG (Zou et al. 2023)** | 🔴 Critical | Foundation of all optimization attacks; 75 papers in DB build on it |
| 2 | **PAIR (Chao et al. 2023)** | 🔴 Critical | Reference for 37 generation-based attack papers |
| 3 | **InstructGPT (Ouyang et al. 2022)** | 🔴 Critical | RLHF foundation; 125 RLHF/PPO papers in DB |
| 4 | **Constitutional AI (Bai et al. 2022)** | 🟡 High | Foundation for RLAIF; 12 CAI papers in DB |
| 5 | **Weak-to-Strong (Burns et al. 2023)** | 🟡 High | Foundation for scalable oversight; 12 papers in DB |
| 6 | **Tamper-Resistant Safeguards (Tamirisa et al. 2025)** | 🟢 Medium | In DB but verify PDF availability |

---

## 7. Next Steps

1. **Review** 92-paper selection with domain experts; prune/replace as needed
2. **Source** 6 missing foundational papers and add to DB
3. **Verify** code/model availability for priority papers
4. **Build** unified evaluation harness (vLLM + GPT-4o judge + SEU metrics)
5. **Execute** Phase 1 (alignment benchmark) → validate → Phase 2-4
6. **Write** experimental findings as SoK Evaluation chapter

---

*Research Agent Draft v3. 92 papers across 51 taxonomy leaves with 7-dimension classification. Modeled after reference SEU paper scale and methodology.*
