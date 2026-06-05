# Research Plan: From Survey Generator to Domain Expert System

**Last updated:** 2026-06-03
**Status:** Brainstorm / Pre-proposal

---

## 0. Conceptual Framework: The System Learns — Not Just the Model

### 0.1 Heuristic Learning (Weng, 2026)

Jiayi Weng recently proposed a new paradigm called **Heuristic Learning (HL)** [1] —
a learning process where:

- The learning subject is a **programmatic code system**, not a neural
  network
- A **coding agent** (LLM) receives feedback from the environment
  (test failures, logs, replays, rewards) and directly modifies the
  codebase to improve behavior
- **No gradient descent** — the update mechanism is code editing
- Old capabilities are solidified as **regression tests, golden
  traces, replays, and version diffs** — explicit, human-readable,
  deletable, and reconstructable artifacts

The core insight: **"Coding agents change the maintenance cost curve
of heuristics. Rules, tests, logs, memory, and patches — once
scattered engineering materials — can now form a continuously updating
Heuristic System (HS)."**

### 0.2 How This Maps to Our Work

We already practiced Heuristic Learning *without naming it as such*:

```
Phase 1: Probe 31 venue+year combos with 10 papers each
  → Feedback: S2 covers CHI 100%, but USS only 3-10%
  → Agent (us + LLM) reads failure logs
  ↓
Phase 2: Write venue-specific strategies
  → fetch_usenix_abstract() for USS
  → fetch_ndss_abstract() for NDSS
  → fetch_crossref_abstract() for any DOI paper
  → Venue-optimized source selection (sources.py table)
  → Agent modifies code to improve coverage
  ↓
Phase 3: Test and harden
  → Each strategy verified with real papers
  → Results documented in devdocs/venue-enrich-strategies.md
  → Old knowledge solidified as documented decisions
```

This is Heuristic Learning applied to **web crawling strategy
discovery**.  The system learned — through trial, error, and code
evolution — to achieve 95%+ abstract coverage across 20 venues,
without training a single model.

### 0.3 From Heuristic Learning to Continual Learning

Weng's key argument is that HL **reframes Continual Learning**:

| Traditional CL | CL via Heuristic Learning |
|----------------|---------------------------|
| "How to update parameters without forgetting?" | "How to maintain a software system that continuously absorbs feedback?" |
| Old knowledge compressed into weights | Old knowledge solidified as regression tests, replays, golden cases |
| Catastrophic forgetting is a parameter problem | Catastrophic forgetting is a **code maintenance** problem |
| Solution: better optimizers | Solution: better code architecture, testing, compression |

For our Domain Expert System, this means:

- When a new paper arrives and contradicts an existing finding → the
  system detects it, stores the conflict explicitly, and updates its
  knowledge — not by retraining a model, but by **writing new
  structured facts + updating the claim graph**
- When a method achieves a new SOTA on a benchmark → the system
  updates the score and marks the old value as superseded, keeping
  both versions with timestamps
- Old knowledge is never "forgotten" — it's archived with evidence
  provenance, available for historical queries

### 0.4 The Two Operations of a Healthy HS

Every Heuristic System needs [1]:

1. **Absorb feedback (吸收反馈):** Ingest new failures, logs, and
   data into the system
2. **Compress history (压缩历史):** Fold accumulated patches back
   into simpler, more maintainable representations

Applied to our Domain Expert:

```
Absorb: New paper → extract facts → detect novelty/conflict → store
Compress: Periodic synthesis — cluster related claims, merge
           redundant findings, simplify the knowledge graph,
           prevent "knowledge code rot"
```

**只增长不压缩的 HS，最后一定会变成屎山代码。** This applies equally
to knowledge bases: without periodic compression, the fact graph
becomes bloated, contradictory, and untrustworthy.

---

## 1. Motivation

### 1.1 What survey_agent does today

```
venue × year → DBLP harvest → abstract enrich → prefilter →
LLM classify → taxonomy → deepdive extract → PDF download →
citation graph → summary → static report
```

It's a **systematic literature survey generator** — crawl a predefined
set of venues, classify papers, and produce a structured markdown/Obsidian
report.  Multi-topic architecture allows sharing one paper pool across
multiple survey topics.  Through Heuristic Learning, the enrichment
pipeline has evolved from a naive S2-only approach to a venue-adaptive
multi-strategy system.

### 1.2 The gap

The current pipeline treats papers as **rows in a database**. After the
report is generated, the raw PDF text is discarded.  The deepdive stage
extracts a handful of structured fields (per-topic), but the vast
majority of knowledge inside PDFs — methodology details, experimental
setups, dataset comparisons, limitation discussions, contradictory
findings — is never systematically stored or made queryable.

### 1.3 What a Domain Expert System would do

Instead of generating one static survey, maintain a **living Heuristic
System (HS)** that grows with each new paper.  The system:

- Ingests and persists **full-text PDF content** by section
- Extracts **structured facts** (method X achieves score Y on dataset Z)
- Supports **cross-paper reasoning** (comparison, contradiction, trend)
- Answers **natural-language queries** with **citations traced to source
  paragraphs**
- **Self-updates** when new papers arrive, marking novel/conflicting
  findings — implements the "absorb feedback" operation
- **Periodically compresses** its knowledge base — implements the
  "compress history" operation

This transforms the system from a "survey printer" into a **domain expert
that researchers can interrogate** — a Heuristic System that learns
through code+data evolution, not model retraining.

### 1.4 Why now: convergence of three trends

1. **LLM coding agents** (Weng 2026) make it feasible to maintain
   heuristic systems that were previously too expensive to curate
2. **Tool paper acceptance** at top SE venues (TradeSweep @ ICSE 2025)
   demonstrates that well-engineered systems with solid evaluation are
   publishable even without algorithmic novelty
3. **Academic literature overload** — venues publish 3,000-7,000 papers
   per year each; researchers cannot keep up through manual reading

---

## 2. Related Work & Positioning

### 2.1 Reference Paper A: TradeSweep (ICSE 2025 Tool Demo)

**TradeSweep: An LLM-Based System for Automated Spreadsheet
Preprocessing** [2]

- **Pipeline:** Natural language request → embedding-based code
  template retrieval → LLM generates pandas code → execute on sample
  data → auto-fix errors → user feedback loop → apply to full dataset
  → save validated code to library
- **Key insight:** Template retrieval reduces LLM hallucination and
  improves code generation reliability; human-in-the-loop provides
  safety while keeping non-programmers in control
- **Evaluation:** 30 preprocessing tasks (automated correctness +
  execution success rate) + 32-participant user study (SUS, task
  completion time, error rate, Likert-scale satisfaction)
- **Baselines:** GPT-4o direct generation, Data Wrangler, Code Interpreter
- **Why it worked:** Clear problem scope + complete system + solid
  two-pronged evaluation + human-in-the-loop framing
- **PDF:** `tmp/ICSE55347.2025.00101.pdf`

**Key lesson for survey_agent:** A tool paper doesn't need algorithmic
novelty. It needs a focused problem, a working end-to-end system, and a
convincing evaluation that demonstrates improvement over baselines.

### 2.2 Reference Paper B: Learning Beyond Gradients (Weng, 2026)

**Learning Beyond Gradients** [1] — blog post by Jiayi Weng, OpenAI

- **Core claim:** Coding agents (LLMs that write and maintain code) can
  produce a new learning paradigm: Heuristic Learning (HL).  Instead of
  gradient-based weight updates, a coding agent continuously reads
  failure logs, modifies code, adds tests, and reviews replays to grow
  a Heuristic System (HS) — a programmatic strategy system that gets
  stronger over time.
- **Key results:** Using GPT-5.4 (Codex) with zero neural network
  training: Atari Breakout reaches theoretical maximum (864), MuJoCo
  Ant achieves 6000+ (deep RL range), Atari57 median HNS surpasses
  PPO.  Method: pure Python code, iteratively refined by the agent.
- **Theoretical contribution:** Reframes Continual Learning from "how
  to update parameters without forgetting" to "how to maintain a
  software system that continuously absorbs feedback."  Old capabilities
  are solidified as regression tests, replays, golden traces —
  explicit forms of knowledge that don't catastrophically forget.
- **Two operations of a healthy HS:** (1) Absorb feedback: write new
  failures, logs, data back into the system; (2) Compress history: fold
  accumulated patches into simpler, more maintainable representations.
- **Coupling complexity:** Defines the limit of what an agent can
  maintain — determined by modularity, testing, logging, state
  reproducibility on the code side, and model capability, context
  length, memory quality, tool quality on the agent side.

**Key lesson for our plan:** The Domain Expert System IS a Heuristic
System.  The paper ingestion → fact extraction → contradiction
detection → knowledge compression pipeline is a concrete
instantiation of HL applied to academic literature.  This framing
gives us a **conceptual contribution** beyond "we built a tool."

### 2.3 Related Systems

| System | Approach | Limitation |
|--------|----------|------------|
| **Elicit / Consensus** | RAG over academic search | Surface-level; no persistent KB; no cross-paper synthesis |
| **OpenAI Deep Research** | LLM agent + web search | Black-box; no persistent KB; no source transparency |
| **PaperQA2** | RAG agent for PDFs | Single-query; no persistent topic model or self-growing corpus |
| **Semantic Scholar** | Citation graph + TLDR | No custom extraction; no contradiction detection |
| **ASReview / LitReview** | Active learning for screening | Only screening; no extraction or synthesis |
| **TradeSweep (ICSE 2025)** | RAG + LLM code-gen for spreadsheets | Different domain; single-session; no persistent knowledge |

**survey_agent Domain Expert** is positioned between these: it maintains
a persistent, topic-scoped, full-text-indexed **Heuristic System** with
structured extraction and cross-paper reasoning — growing and improving
through continuous feedback, not retraining.

---

## 3. System Architecture: A Heuristic System for Academic Literature

### 3.1 High-Level Overview

```
┌──────────────────────────────────────────────────────────────┐
│              Domain Expert System (Heuristic System)          │
│                                                               │
│  ┌───────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │ Ingest    │ → │ Extract  │ → │ Index    │ → │ Query    │→│
│  │ (Absorb)  │   │ Facts    │   │ Memory   │   │ Interface│ User
│  └───────────┘   └──────────┘   └──────────┘   └──────────┘ │
│        ↑                                              │      │
│   New papers                                    NL queries    │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ Knowledge Base (per-topic, grows over time)            │   │
│  │  ├─ Full-text chunks (section-aware, vector-indexed)   │   │
│  │  ├─ Structured facts (method/dataset/metric/score)     │   │
│  │  ├─ Cross-paper relations (contradiction/confirmation) │   │
│  │  ├─ Claim graph with evidence provenance               │   │
│  │  └─ Versioned history (old claims superseded, not lost)│   │
│  └───────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ Maintenance Loop (Heuristic Learning)                  │   │
│  │  ├─ Absorb: new paper → detect novelty/conflict        │   │
│  │  ├─ Compress: periodic claim synthesis + dedup         │   │
│  │  └─ Verify: regression-test old answers against new KB │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Layer 1: Knowledge Ingestion (Absorb Feedback)

**Input:** PDF full-text (from existing `s04_fulltext` stage)

```
PDF → pdfplumber/marker-pdf → section-aware text
  ↓
Split by section (Abstract / Introduction / Method /
  Experiments / Discussion / Conclusion)
  ↓
Embed each chunk → store in vector DB (topic-scoped)
  ↓
LLM extraction → structured facts + evidence spans
```

**Structured extraction schema (per-topic, configurable):**

| Fact Type | Example | Evidence Span |
|-----------|---------|---------------|
| Method claim | "BERT achieves 93.2% F1 on SQuAD 2.0" | §4.2, para 3 |
| Dataset usage | "Method evaluated on ImageNet-1K" | §5.1, para 1 |
| Contradiction | "Unlike Smith et al., we find that..." | §6, para 2 |
| Limitation | "Our approach requires GPU with ≥24GB VRAM" | §7, para 1 |
| Comparison | "Outperforms baseline X by 3.4 points" | §5.3, Table 2 |

### 3.3 Layer 2: Knowledge Synthesis (Cross-Paper Reasoning)

**Query types the expert can answer:**

| Query Type | Example | Mechanism |
|-----------|---------|-----------|
| Factual lookup | "What dataset does Method X use?" | Vector search + extract evidence span |
| Comparison | "Method A vs Method B on benchmark W?" | Dual retrieval + structured comparison table |
| Trend | "How has accuracy improved 2023-2025?" | Temporal aggregation of metric claims |
| Contradiction | "Do any papers disagree with Claim Y?" | Claim similarity + negation detection |
| Evidence strength | "How well-replicated is Finding Z?" | Cross-paper claim count + independence check |
| SOTA snapshot | "Best reported score on benchmark W?" | Metric aggregation with date + setup notes |
| Gap analysis | "What's NOT been tried in this area?" | Taxonomy coverage gaps + limitation synthesis |

**Implementation:**
```
User query → embedding → multi-chunk retrieval (top-k across papers)
  → rerank by relevance + diversity
  → LLM multi-document synthesis
  → generate answer with inline citations
  → structured output: answer + evidence list + confidence
```

### 3.4 Layer 3: Self-Growing Knowledge (Maintenance Loop)

This is where the system becomes a **Heuristic System** in Weng's sense.

**Absorb Feedback (triggered by new paper ingestion):**
```
New paper ingested → extract facts
  → compare against existing knowledge base
  → classification:
      ├─ NEW: previously unseen method/dataset/claim
      ├─ UPDATE: improves SOTA on existing benchmark
      ├─ CONFIRM: replicates existing finding (strengthens evidence)
      └─ CONFLICT: contradicts existing claim (stored explicitly)
  → notification + knowledge graph update
```

**Compress History (triggered periodically or by user):**
```
Trigger: KB size exceeds threshold, or user requests synthesis
  → Cluster similar claims across papers
  → Merge redundant evidence chains
  → Identify stale/contradicted claims → mark as superseded
  → Generate updated "consensus snapshot"
  → Old versions preserved (versioned history, not deleted)
```

This addresses the core challenge Weng identifies: **"只增长不压缩的
HS，最后一定会变成屎山代码"** — a knowledge base that only grows
without compression becomes untrustworthy.

### 3.5 Interaction Model

**Mode A: Interactive Query (replaces static report)**
- Natural language question → cited answer with evidence spans
- "Show me the evidence" → expand to source paragraphs
- "Compare X and Y" → side-by-side structured comparison table
- "What's new since I last checked?" → diff-style update

**Mode B: Guided Survey Generation (enhanced report)**
- Still produces the static survey output
- But every claim in the survey is **linked to source evidence**
- Reader can click through to see original paragraphs
- Survey becomes a "view" into the knowledge base, not the product

---

## 4. Heuristic Learning in Action: Case Study

### 4.1 What we already learned (enrichment strategies)

Our enrichment pipeline evolution is a microcosm of Heuristic Learning:

| HL Concept | Our Enrichment Story |
|------------|---------------------|
| **Coding agent** | Human + LLM (us + Claude) analyzing probe results |
| **Feedback** | 31 venue+year combos, 10 papers each → coverage stats |
| **Absorb** | Identified gaps: USS S2 coverage ~3%, TOSEM 2023 ~50% |
| **Code update** | Wrote `strategies/crossref.py`, `strategies/usenix.py` |
| **Compress** | Consolidated 31 test results into `_VENUE_SOURCES` table |
| **Verify** | Re-ran tests → TOSEM 2023: 50% → 99% coverage |

At each step, the system *learned* — not by training a model, but by:
1. Probing the environment (test queries)
2. Identifying failure modes (low coverage venues)
3. Writing new code strategies
4. Integrating them into the pipeline
5. Verifying improvement

This is exactly the HL loop Weng describes in [1].

### 4.2 The Domain Expert will learn the same way

As the system ingests more papers and users ask more questions, it will:

1. **Learn better extraction patterns** — when a user corrects an
   extracted fact, the agent updates the extraction prompt/template
2. **Discover cross-paper patterns** — when multiple papers report
   similar results, the system detects consensus
3. **Identify knowledge gaps** — when a user asks a question the system
   can't answer, it flags "need more papers on X" or "need better
   extraction for Y"
4. **Grow per-topic expertise** — each topic's knowledge base evolves
   independently, with its own taxonomy, extraction schema, and
   verified claims

---

## 5. Evaluation Plan

### 5.1 Automated Evaluation

**Dataset construction:**
- Select 3 established research areas within the crawled venues
  (e.g., "GUI Agent", "LLM Code Generation", "Federated Learning Security")
- Manually construct ground truth for each:
  - Key papers list (recall target, 30-50 papers)
  - SOTA claims (20-30 per area)
  - Known contradictions (5-10 per area)
  - Method taxonomy (hierarchical, 3-4 levels)

**Metrics:**
| Metric | Measures |
|--------|----------|
| Paper recall@k | % of expert-identified key papers found in KB |
| Claim precision | % of extracted claims that are factually correct |
| Evidence accuracy | % of claims with correct source paragraph |
| Comparison correctness | Binary: is A vs B comparison direction correct? |
| Contradiction recall | % of known contradictions detected |
| Answer quality (LLM-as-judge) | GPT-4 scores synthesis quality on 1-5 Likert |
| Update reliability | % of new papers correctly classified as NEW/UPDATE/CONFLICT |
| KB staleness | Time from paper publication to KB update |

### 5.2 User Study

**Participants:** 10-15 researchers (PhD students, postdocs) in SE/AI/ML

**Task design (within-subjects, counterbalanced):**
1. **Control:** Participants use Google Scholar + ChatGPT to answer
   5 research questions (30 min)
2. **Treatment:** Same 5 questions using Domain Expert System (30 min)

**Measurements:**
- Time to answer
- Answer correctness (blind expert grading)
- Source traceability (% of claims with verifiable citations)
- SUS (System Usability Scale)
- NASA-TLX (cognitive load)
- Qualitative: "Would you use this in your own research? Why/why not?"

### 5.3 Baselines

| Baseline | Description |
|----------|-------------|
| **ChatGPT-4 + web search** | User asks ChatGPT with browsing enabled |
| **Semantic Scholar + manual** | User searches S2, reads abstracts, synthesizes |
| **Elicit / Consensus** | Existing AI research tools (RAG-based) |
| **survey_agent (static)** | Current static report output (no interactive query) |
| **Domain Expert (ours)** | Full interactive query system with evidence traces |

### 5.4 Longitudinal Evaluation

Deploy the system with one active topic for 3 months:
- Track: new papers ingested, user queries, answer ratings, KB growth
- Measure in situ: does the system get *better* over time as more
  papers are added? (Heuristic Learning hypothesis)
- Report: qualitative case studies of novel/conflicting findings
  detected

---

## 6. Novelty Argument

The individual components (RAG, LLM extraction, vector search) are not
novel.  The contribution is the **integrated architecture** that:

1. **Instantiates Heuristic Learning for academic literature** — the
   first system to apply Weng's HL paradigm not to game-playing or
   robotics, but to knowledge curation and literature synthesis
2. **Maintains a self-growing knowledge base** that detects
   novel/conflicting findings and compresses history — two operations
   that define a healthy Heuristic System [1]
3. **Traces every answer to source evidence** at paragraph granularity
   — addressing hallucination in a verifiable, regression-testable way
4. **Supports structured cross-paper reasoning** (comparison,
   contradiction, trend) rather than simple factoid retrieval
5. **Evolves through code+data co-evolution** — the enrichment
   strategies, extraction schemas, and compression heuristics all
   improve through feedback, not retraining

This is both a **systems contribution** (a working end-to-end tool)
and a **conceptual contribution** (demonstrating that HL applies to
knowledge work, not just control tasks).

---

## 7. Target Venues

| Venue | Track | Fit | Notes |
|-------|-------|-----|-------|
| **ICSE** | Tool Demo | ⭐⭐⭐ | Same track as TradeSweep [2]; strongest fit |
| **ASE** | Tool Demo | ⭐⭐⭐ | Broader tool focus; good fit |
| **FSE** | Tool Demo | ⭐⭐⭐ | Similar prestige to ICSE |
| **ICSE** | NIER | ⭐⭐ | Needs stronger novelty framing; HL angle helps |
| **EMNLP** | System Demo | ⭐⭐ | NLP audience; domain expert angle works |
| **AAAI** | Demo | ⭐ | Broader AI; less domain fit |

**Primary target:** ICSE 2027 or ASE 2027 Tool Demo
(deadlines typically Aug-Sep 2026 for ICSE, Nov-Dec 2026 for ASE)

---

## 8. Timeline (Draft, 18 weeks)

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| **Phase 1: Core Ingestion** | Week 1-3 | PDF section parser, chunking + embedding, vector store |
| **Phase 2: Fact Extraction** | Week 4-6 | Structured extraction pipeline, evidence spans, per-topic schema |
| **Phase 3: Query & Synthesis** | Week 7-8 | Multi-document RAG, comparison, contradiction detection |
| **Phase 4: Self-Growth** | Week 9-10 | Incremental new-paper update, novelty/conflict classification, history compression |
| **Phase 5: Evaluation** | Week 11-14 | Ground truth construction, automated eval, user study, longitudinal pilot |
| **Phase 6: Paper Writing** | Week 15-18 | System description, evaluation analysis, related work, HL framing |

---

## 9. Open Questions

1. **Vector DB choice:** LanceDB (embedded, no server) vs ChromaDB
   (more mature) vs pgvector (heavier but integrates with SQLite)
2. **PDF parsing quality:** Current `pdfplumber` loses structure.
   Consider `marker-pdf`, `docling`, or `grobid` for section-aware
   extraction
3. **Fact schema design:** Fully per-topic (max flexibility) vs shared
   core + per-topic extensions?
4. **LLM cost model:** Full-text extraction of all papers is expensive.
   Rough estimate: 500 papers × 10k tokens × DeepSeek ≈ $5-10 per
   topic.  Need caching and incremental extraction strategy
5. **Compression frequency:** How often to trigger "compress history"?
   Per paper? Per week? User-driven?
6. **Evaluating Heuristic Learning:** How to measure that the system
   "gets better over time"?  Need longitudinal metric: answer quality
   vs KB age/size

---

## 10. Appendix: Reference Summaries

### A. TradeSweep (ICSE 2025 Tool Demo) [2]

- **Problem:** Non-programmers struggle with spreadsheet data
  preprocessing (missing values, type conversion, encoding, etc.)
- **Approach:** Natural language request → embedding-based code
  template retrieval → LLM generates pandas code → execute on sample →
  auto-fix errors → user feedback → apply to full dataset → save new
  code to library
- **Key insight:** Template retrieval reduces LLM hallucination and
  improves code correctness; human-in-the-loop provides safety
- **Evaluation:** 30 preprocessing tasks (automated) + 32-participant
  user study (SUS, task time, error rate, Likert-scale satisfaction)
- **Baselines:** GPT-4o direct generation, Data Wrangler, Code Interpreter
- **Venue:** ICSE 2025 Tool Demo Track
- **PDF:** `tmp/ICSE55347.2025.00101.pdf`

### B. Learning Beyond Gradients (Weng, 2026) [1]

- **Problem:** Continual Learning is fundamentally limited by
  catastrophic forgetting in neural networks
- **Core idea:** Heuristic Learning (HL) — a coding agent maintains a
  growing Heuristic System (HS) through continuous feedback (test
  failures, logs, replays, rewards).  No gradient descent; updates
  happen through code modification
- **Key results:** GPT-5.4 Codex achieves Atari Breakout 864 (theoretical
  max), MuJoCo Ant 6000+, Atari57 median HNS surpassing PPO — all with
  pure Python code, zero neural network training
- **Key insight:** HL reframes Continual Learning from "how to update
  parameters" to "how to maintain a software system that absorbs
  feedback." Old capabilities are solidified as regression tests,
  replays, golden traces — explicit, verifiable forms of memory
- **Two operations:** Absorb feedback + Compress history
- **Coupling complexity:** Defines the maintenance limit of an HS,
  determined by code modularity + agent capability
- **URL:** https://trinkle23897.github.io/learning-beyond-gradients/

---

## References

[1] Weng, J. (2026). *Learning Beyond Gradients.* Blog post.
    https://trinkle23897.github.io/learning-beyond-gradients/

[2] TradeSweep: An LLM-Based System for Automated Spreadsheet
    Preprocessing. ICSE 2025 Tool Demo Track.
    PDF: `tmp/ICSE55347.2025.00101.pdf`
