# Research Plan: Domain Expert System via Heuristic Learning

**Last updated:** 2026-06-03
**Status:** Brainstorm / Pre-proposal

---

## 0. Conceptual Framework

### 0.1 Heuristic Learning (Weng, 2026)

Jiayi Weng (OpenAI) recently proposed **Heuristic Learning (HL)** [1]:

> A coding agent maintains a growing Heuristic System (HS) through
> continuous feedback — reading failures, modifying code, adding tests,
> reviewing replays. No gradient descent. The update mechanism is code
> editing. Old capabilities are solidified as regression tests,
> replays, golden traces — explicit, human-readable, deletable,
> reconstructable artifacts.

**Two essential operations for a healthy HS:**
1. **Absorb feedback:** Ingest new data, failures, logs into the system
2. **Compress history:** Fold accumulated patches into simpler, more
   maintainable representations — without this, any HS becomes legacy
   code

Core insight: *"Coding agents change the maintenance cost curve of
heuristics. Rules, tests, logs, memory, and patches — once scattered
engineering materials — can now form a continuously updating Heuristic
System."*

### 0.2 How survey_agent Already Practices HL

We already practiced Heuristic Learning without naming it:

| HL Phase | Our Enrichment Story |
|----------|---------------------|
| **Probe environment** | Tested 31 venue+year combos, 10 papers each |
| **Read failure logs** | USS S2 coverage ~3%, TOSEM 2023 ~50%, CHI 100% |
| **Absorb feedback** | Identified: need Crossref for DOIs, usenix.org for USS |
| **Agent modifies code** | Wrote `strategies/crossref.py`, `sources.py` venue table |
| **Verify** | TOSEM 2023: 50% → 99% coverage |
| **Compress history** | Consolidated 31 test results into `_VENUE_SOURCES` table |
| **Knowledge solidified** | `devdocs/venue-enrich-strategies.md` as regression artifact |

The system *learned* to achieve 95%+ abstract coverage across 20 venues
through code evolution, not model training.

### 0.3 The Big Idea: HL Applied to Academic Knowledge

Weng demonstrated HL on game-playing (Atari, MuJoCo) and robotics
control.  We propose applying HL to a fundamentally different domain:
**academic knowledge curation and literature synthesis.**

| Dimension | Weng's Atari/MuJoCo | Our Domain Expert |
|-----------|--------------------|--------------------|
| Environment | Game engine, physics sim | PDF full-text, user queries |
| Feedback | Reward signal, video replay | Missing facts, user corrections, contradiction detection |
| Policy | Python heuristic strategy | Extraction pipeline + knowledge graph |
| State | Game state variables | Structured facts, evidence spans, claim graph |
| Memory | trials.jsonl, summary.csv | Vector DB, fact DB, versioned claim history |
| Regression test | Replay at fixed seed | Query answer consistency, fact verification |
| Compression | Simplify policy code | Cluster claims, merge evidence, mark superseded |

**Novel contribution: HL has never been applied to knowledge work.**
Our system would be the first to demonstrate that the same paradigm —
agent-driven code+data co-evolution without model retraining — works
for building domain expertise, not just game-playing.

---

## 1. Motivation

### 1.1 What survey_agent does today

```
venue × year → DBLP harvest → abstract enrich → prefilter →
LLM classify → taxonomy → deepdive extract → PDF download →
citation graph → summary → static report
```

A systematic literature survey generator with multi-topic architecture
and venue-adaptive enrichment developed through HL.

### 1.2 The gap

Papers are treated as database rows. After report generation, PDF full
text is discarded. Structured extraction captures only a few fields
per paper. The vast knowledge inside PDFs — methodology details,
experimental setups, dataset comparisons, limitation discussions,
contradictory findings — is never systematically stored or queried.

### 1.3 The vision: a living Heuristic System for academic literature

```
Static survey generator                    Living Domain Expert
     ↓                                           ↓
Generate report → discard PDFs          Ingest PDFs → store forever
                                        Extract facts → structured knowledge
                                        Answer queries → cite sources
                                        New papers → detect novelty/conflict
                                        Periodic compression → stay healthy
```

The system becomes a **Heuristic System** that grows with each paper,
maintained by an LLM agent through the HL feedback loop.

### 1.4 Why now

Three converging trends:

1. **LLM coding agents** (Weng 2026) make it feasible to maintain
   heuristic systems whose maintenance cost was previously prohibitive
2. **Tool paper acceptance** at top SE venues (TradeSweep @ ICSE 2025)
   proves that well-engineered systems with solid evaluation are
   publishable without algorithmic novelty
3. **Academic literature overload** — top venues publish 3,000-7,000
   papers/year each; researchers cannot keep up through manual reading

---

## 2. Related Work

### 2.1 Learning Beyond Gradients (Weng, 2026) [1]

Blog post proposing Heuristic Learning as the "next paradigm" after
pretrain → RLHF → large-scale RL.  Key results: Atari Breakout reaches
theoretical max (864 points), MuJoCo Ant achieves 6000+ (deep RL
range) — all with pure Python code, zero neural network training.

**Relevance to us:** Provides the conceptual framework.  Our Domain
Expert System is a concrete instantiation of HL applied to a new
domain (academic knowledge work).

> *"凡是可以被持续迭代的，都开始能被解决。"*
> — Whatever can be iterated continuously, begins to be solvable.

### 2.2 TradeSweep (ICSE 2025 Tool Demo) [2]

LLM-based spreadsheet preprocessing with RAG-based code template
retrieval + human-in-the-loop feedback.  30-task automated evaluation
+ 32-participant user study.

**Relevance to us:** Demonstrates publication viability.  Same venue
we're targeting.  Proof that "RAG + LLM generation + evaluation" is
sufficient for a tool paper.

### 2.3 Related Systems

| System | Approach | Gap |
|--------|----------|-----|
| Elicit / Consensus | RAG over academic search | No persistent KB, no cross-paper reasoning |
| OpenAI Deep Research | LLM agent + web search | Black-box, no source transparency |
| PaperQA2 | RAG agent for PDFs | Single-query, no self-growing corpus |
| Semantic Scholar | Citation graph + TLDR | No custom extraction, no contradiction detection |

### 2.4 Structural Comparison: TradeSweep [2] vs Our Domain Expert

TradeSweep (ICSE 2025 Tool Demo) is our closest analogue in terms of
venue, scope, and contribution style.  Comparing the two systems
reveals structural parallels — and where our system has greater
depth — that strengthen our publication case.

**Similarities (why we can target the same venue):**

| Dimension | TradeSweep [2] | Our Domain Expert |
|-----------|---------------|-------------------|
| **Track** | ICSE Tool Demo | ICSE/ASE Tool Demo (target) |
| **Problem** | Non-programmer spreadsheet cleaning | Researcher literature overload |
| **Core tech** | RAG + LLM generation + execution | RAG + LLM extraction + synthesis |
| **Human-in-loop** | User confirms sample results, provides NL feedback | User corrects facts, asks NL questions |
| **Growing library** | Saved code templates + pipelines | Growing knowledge base + fact graph |
| **Feedback loop** | Execution error → LLM revises code | Missing/contradicted fact → agent updates KB |
| **Novelty style** | Engineering integration, not algorithm | Engineering integration + conceptual framework |
| **Evaluation** | 30-task automated + 32-user study | Planned: similar structure, expanded to longitudinal |

**Differences (where our system goes deeper):**

| Dimension | TradeSweep [2] | Our Domain Expert |
|-----------|---------------|-------------------|
| **Lifetime** | Single session | Persistent, grows over months/years |
| **What grows** | Code library (human-curated) | Knowledge base (agent-maintained) |
| **Memory** | Session-scoped, resets each use | Persistent: vector DB + fact DB + version history |
| **Continual aspect** | No — each session independent | Yes — KB accumulates, old knowledge archived |
| **Compression** | N/A | Claim clustering, evidence merging (core HL op) |
| **Source provenance** | Not a concern | Paragraph-level evidence tracing (critical for trust) |
| **Conceptual framework** | Plain RAG + code generation | Heuristic Learning (Weng 2026) — novel framing |
| **Domain scope** | One tool (spreadsheets) | One topic per expert instance, multi-topic architecture |
| **Scale of prior work** | Code templates (dozens) | 20 venues, 70k+ papers, 36k+ PDFs, multi-topic pipeline |

**Why this comparison matters:**

TradeSweep demonstrates that an ICSE Tool Demo paper requires:
1. A well-defined user pain point
2. A working end-to-end system
3. Dual evaluation (automated + user study)
4. A clear feedback loop (execution → revision → verification)

Our Domain Expert satisfies all four — and additionally provides:
5. A conceptual framework (Heuristic Learning applied to knowledge work)
6. A longitudinal dimension (the system improves over time)
7. Stronger evidence provenance (paragraph-level citation tracing)

The structural parallels with TradeSweep validate our venue choice.
The differences establish our novelty — we are not doing "RAG for
papers" but building a self-growing Heuristic System whose maintenance
is enabled by LLM coding agents, following Weng's paradigm.

---

## 3. How HL Maps to Our System

### 3.1 The Mapping

```
Weng's Heuristic Learning              Our Domain Expert
─────────────────────────              ─────────────────

Coding Agent (LLM writes code)    →    LLM writes/updates extraction
                                        schemas, fact templates,
                                        compression rules

Environment                        →    PDF corpus + user queries +
                                        feedback loop

Feedback (reward, test failure,   →    Missing facts, user corrections,
 replay, log)                          contradiction detected, stale
                                        claim flagged

Policy (heuristic code, rules)    →    Extraction pipeline + fact
                                        verification + answer synthesis

State (variables, detectors,      →    Knowledge graph state: claims,
 cache)                                 evidence spans, relations,
                                        version history

Memory (trials.jsonl,             →    Vector DB (full text) + fact DB
 summary.csv, replay videos)           (structured) + claim graph
                                        (relations) + version log

Regression test (fixed-seed       →    Query consistency check: ask
 replay to verify score)               same question, verify answer
                                        hasn't degraded

Compress history (simplify        →    Periodic claim clustering +
 policy, remove dead rules)            evidence merging + stale
                                        claim archival
```

### 3.2 The Feedback Loop

```
                    ┌──────────────────────┐
                    │   Domain Expert HS    │
                    └──────────┬───────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
    New paper arrives    User asks question   User corrects fact
          │                    │                    │
          ▼                    ▼                    ▼
    Extract facts        Retrieve evidence    Flag incorrect claim
    Compare to KB        Synthesize answer    Log as failure case
          │                    │                    │
          ▼                    ▼                    ▼
    NEW / UPDATE /       Return answer        Agent updates
    CONFIRM / CONFLICT   with citations       extraction schema
          │                    │                    │
          └────────────────────┼────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   Periodic Compress   │
                    │   Cluster claims      │
                    │   Merge evidence      │
                    │   Archive superseded  │
                    │   Generate consensus  │
                    └──────────────────────┘
```

### 3.3 Managing Coupling Complexity

Weng defines **coupling complexity** as the primary constraint on HS
growth — how many interacting rules, states, and feedback sources the
agent can manage simultaneously.

Our defenses against coupling explosion:

| Defense | Implementation |
|---------|---------------|
| **Modularity** | Per-topic isolation; independent knowledge bases |
| **Schema boundaries** | Structured extraction schema per topic |
| **Versioned history** | Old claims archived, not deleted |
| **Regression tests** | Query consistency checks |
| **Explicit memory** | Vector DB + fact DB (not compressed into weights) |
| **Periodic compression** | Claim clustering, evidence merging |

---

## 4. System Architecture

### 4.1 Overview

```
┌──────────────────────────────────────────────────────────────┐
│              Domain Expert System (Heuristic System)          │
│                                                               │
│  ┌───────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │ Ingest    │ → │ Extract  │ → │ Query    │ ← │ User     │ │
│  │ (Absorb)  │   │ Facts    │   │ Interface│   │ Input    │ │
│  └───────────┘   └──────────┘   └──────────┘   └──────────┘ │
│        ↑                                               │      │
│   New papers                                    NL questions  │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ Knowledge Base (per-topic, growing over time)          │   │
│  │  ├─ Full-text chunks (section-aware, vector-indexed)   │   │
│  │  ├─ Structured facts (method/dataset/metric/score)     │   │
│  │  ├─ Claim graph with evidence provenance               │   │
│  │  └─ Versioned history (superseded claims preserved)    │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐   │
│  │ Maintenance Loop (HL implementation)                   │   │
│  │  ├─ Absorb: new paper → extract → classify change type │   │
│  │  ├─ Compress: cluster claims, merge evidence, archive  │   │
│  │  └─ Verify: regression-query old answers               │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 Layer 1: Absorb Feedback (Ingestion)

```
PDF → section-aware parsing → chunk by section → embed → vector store
  ↓
LLM extraction → structured facts + evidence spans
  ↓
Compare against existing knowledge → classify: NEW/UPDATE/CONFIRM/CONFLICT
```

### 4.3 Layer 2: Query & Synthesis

Supported query types:
- **Factual:** "What dataset does Method X use?"
- **Comparison:** "Method A vs Method B on benchmark W?"
- **Trend:** "How has accuracy improved 2023-2025?"
- **Contradiction:** "Do any papers disagree with Claim Y?"
- **Evidence strength:** "How well-replicated is Finding Z?"
- **Gap analysis:** "What's NOT been tried in this area?"

### 4.4 Layer 3: Compress History (Maintenance)

```
Trigger: KB threshold, periodic schedule, or user request
  → Cluster similar claims across papers
  → Merge redundant evidence chains
  → Identify stale/contradicted claims → mark superseded
  → Generate consensus snapshot
  → Old versions preserved (versioned, not deleted)
```

---

## 5. What Stays, What's New

### 5.1 Reused from survey_agent

| Component | Role |
|-----------|------|
| `s00_harvest` | Paper discovery (shared pool) |
| `s01_enrich` | Venue-adaptive abstract enrichment (HL-evolved) |
| `s03_classify` | Relevance filtering per topic |
| `s04_fulltext` | PDF download → becomes ingestion feeder |
| `s07_taxonomy` | Schema for method/domain classification |
| `s08_citation` | Evidence graph backbone |
| Topics YAML | Per-topic expert config |
| LLM cache | Cost control |

### 5.2 New Components

| Component | Est. Effort | Description |
|-----------|-------------|-------------|
| PDF section parser | 3-4 days | Section-aware extraction (not raw dump) |
| Vector store | 1-2 days | LanceDB/ChromaDB, per-topic collections |
| Chunking + embedding | 1 day | Semantic chunking, embedding API |
| Fact extractor | 5-7 days | Structured extraction with evidence spans |
| Multi-document RAG | 3-5 days | Retrieval → rerank → synthesis |
| Contradiction detector | 5-7 days | Claim similarity + negation detection |
| Incremental updater | 3-4 days | New paper → diff → classify change type |
| Query interface | 3-5 days | TUI chat + optional web UI |
| Compression pipeline | 3-5 days | Claim clustering, evidence merging |
| Evaluation framework | 7-10 days | Ground truth + metrics + user study |

**Total estimated effort:** 35-50 days (one person full-time)

---

## 6. Evaluation Plan

### 6.1 Automated Evaluation

Select 3 research areas within crawled venues.  Construct ground truth:
key papers, SOTA claims, known contradictions, method taxonomy.

**Metrics:**
| Metric | Measures |
|--------|----------|
| Paper recall@k | Expert-identified key papers found |
| Claim precision | % of claims factually correct |
| Evidence accuracy | % of claims with correct source paragraph |
| Contradiction recall | % of known contradictions detected |
| Answer quality | LLM-as-judge, Likert 1-5 |
| Update accuracy | % of new papers correctly classified (NEW/UPDATE/CONFLICT) |

### 6.2 User Study

- 10-15 researchers (PhD students, postdocs)
- Within-subjects, counterbalanced: Google Scholar+ChatGPT vs Domain Expert
- Measurements: time, correctness, source traceability, SUS, NASA-TLX

### 6.3 Baselines

- ChatGPT-4 + web search
- Semantic Scholar + manual search
- Elicit / Consensus (if API available)
- survey_agent static report (our own current system)

### 6.4 Longitudinal Pilot

Deploy 1 active topic for 3 months:
- Track: papers ingested, queries asked, answer ratings, KB growth
- Verify HL hypothesis: does the system get *better* over time?

---

## 7. Novelty Framing

1. **First application of Heuristic Learning to knowledge work** —
   all prior HL results are on games/robotics; we demonstrate the
   paradigm on academic knowledge curation
2. **Self-growing knowledge base with verified evidence provenance**
   — every claim traceable to source paragraph; old knowledge
   archived, not forgotten
3. **Two core HL operations instantiated** — Absorb (new paper →
   detect change type) and Compress (periodic claim synthesis)
4. **Coupling complexity managed through architecture** — modular
   per-topic isolation, structured schemas, versioned history,
   regression testing

The combination of HL framework + complete tool system + rigorous
evaluation is sufficient for ICSE/ASE Tool Demo.

---

## 8. Target Venue

**Primary:** ICSE 2027 or ASE 2027 Tool Demo Track
(TradeSweep was ICSE 2025 Tool Demo — same track, same community)

---

## 9. Timeline

| Phase | Duration | Deliverables |
|-------|----------|-------------|
| Phase 1: Ingestion | Week 1-3 | PDF parser, chunking, embedding, vector store |
| Phase 2: Fact Extraction | Week 4-6 | Structured extraction, evidence spans, per-topic schema |
| Phase 3: Query & Synthesis | Week 7-8 | Multi-document RAG, comparison, contradiction detection |
| Phase 4: Self-Growth | Week 9-10 | Incremental update, novelty/conflict classification, compression |
| Phase 5: Evaluation | Week 11-14 | Ground truth, automated eval, user study, longitudinal pilot |
| Phase 6: Writing | Week 15-18 | System description, results analysis, related work |

---

## 10. Open Questions

1. **PDF parser:** pdfplumber → marker-pdf / docling / grobid for
   section-aware extraction?
2. **Vector DB:** LanceDB (embedded) vs ChromaDB (mature) vs pgvector?
3. **Fact schema:** Fully per-topic or shared core + extensions?
4. **Compression trigger:** Per-paper? Per-week? User-driven?
5. **Evaluating HL:** How to measure "system gets better over time"?
   Longitudinal answer quality vs KB age?
6. **Model choice:** DeepSeek for cost, or GPT/Claude for quality?

---

## References

[1] Weng, J. (2026). *Learning Beyond Gradients.*
    https://trinkle23897.github.io/learning-beyond-gradients/

[2] Lee, C.-T., Neeser, A., Xu, S., Katyan, J., Cross, P., Pathakota, S.,
    Norman, M., Simeone, J., Chandrasekaran, J., & Ramakrishnan, N. (2025).
    Can an LLM Find Its Way around a Spreadsheet? In *Proceedings of the
    IEEE/ACM 47th International Conference on Software Engineering (ICSE '25)*,
    pp. 294–306. IEEE Press. DOI: 10.1109/ICSE55347.2025.00101
