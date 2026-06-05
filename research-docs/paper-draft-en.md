# Domain Expert: An LLM-Maintained Heuristic System for Academic Domain Research

**Target Venue:** ICSE/ASE 2027 Tool Demo Track

---

## Abstract

Literature reviews are the backbone of academic research, yet producing
a rigorous, up-to-date understanding of a research area is extremely
labor-intensive.  Researchers must continuously track new work, compare
methods, identify contradictions, and synthesize findings — a process
of **ongoing domain investigation** that remains largely manual and
unreproducible.  We present **Domain Expert**, a system that ingests
full-text academic papers, extracts structured facts with
paragraph-level provenance, and maintains a self-growing knowledge
base that supports cross-paper reasoning, contradiction detection,
and evidence-traced natural language queries — functioning as a
persistent research assistant rather than a one-shot report generator.  Our key insight is that the system itself is a
**Heuristic System** in the sense of Weng (2026): an LLM coding agent
maintains and evolves the extraction schemas, fact verification
rules, and knowledge compression heuristics through continuous
feedback — reading failure logs, incorporating user corrections,
and periodically compressing the knowledge graph.  No model
retraining is involved; all learning occurs through code+data
co-evolution.  We build on a mature multi-topic literature pipeline
that already crawls 20+ SE/Security/AI venues and manages 70,000+
papers, whose enrichment strategies were themselves discovered
through the Heuristic Learning process we now formalize.  Evaluation
plans include automated benchmarks on 3 research areas and a user
study with 10–15 researchers comparing our system against
GPT-4+search, Semantic Scholar, and static research reports.

---

## 1. Introduction

Academic research is growing at an unprecedented rate, making it
increasingly difficult for researchers to sustain a deep, up-to-date
understanding of any field.  Top venues in software engineering,
security, and AI each publish thousands of papers annually.
Researchers must continuously investigate new work, compare methods,
identify contradictions, and synthesize findings — an **ongoing
domain investigation** that remains largely manual and unreproducible.

Existing tools address fragments of this problem.  Semantic Scholar
provides citation graphs and TLDR summaries.  Elicit and Consensus
offer RAG-based search over academic databases.  PaperQA2 enables
question-answering over individual PDFs.  But none of these maintain a
**persistent, growing, verifiable knowledge base** that accumulates
structured facts over time and supports cross-paper reasoning with
evidence provenance.

We present **Domain Expert**, a system that transforms domain investigation
from a one-shot generation task into a **living Heuristic System**.  The system ingests PDF full-text, extracts structured facts,
and answers natural language queries with citations traced to source
paragraphs.  It maintains a per-topic knowledge base that grows with
each new paper and periodically compresses itself to prevent knowledge
bloat.  The extraction schemas, fact verification rules, and
compression heuristics are themselves maintained by an LLM coding agent
through continuous feedback — an instantiation of the **Heuristic
Learning** paradigm recently proposed by Weng (2026).

**Contributions:**

1. A conceptual framework that applies Heuristic Learning (Weng 2026)
   to academic knowledge curation — a domain HL has never been
   demonstrated on
2. A working end-to-end system that ingests PDF full-text, extracts
   structured facts with paragraph-level evidence provenance, and
   supports cross-paper reasoning via natural language queries
3. A self-growing knowledge base with two core HL operations: **Absorb**
   (new paper → detect novelty/contradiction) and **Compress**
   (periodic claim clustering and evidence merging)
4. A case study of Heuristic Learning in practice: the discovery of
   venue-adaptive enrichment strategies that achieve 95%+ abstract
   coverage across 20 venues through code evolution, not model training

---

## 2. Background and Motivation

### 2.1 Heuristic Learning

Weng (2026) recently proposed **Heuristic Learning (HL)** as a new
learning paradigm.  The core claim: a coding agent (an LLM that writes
and maintains code) can produce a learning system that improves over
time without gradient descent.  The agent reads failure logs, modifies
code, adds tests, and reviews replays to grow a **Heuristic System
(HS)** — a programmatic strategy system that gets stronger through
code evolution.

A healthy HS requires two operations:

1. **Absorb feedback:** Ingest new failures, logs, and data into the
   system
2. **Compress history:** Fold accumulated patches into simpler, more
   maintainable representations — *"只增长不压缩的 HS，最后一定会变
   成屎山代码"* (an HS that only grows without compression will
   inevitably become legacy code)

Weng demonstrated HL on Atari games (Breakout reaching theoretical
maximum 864 points) and MuJoCo robotics (Ant achieving 6000+ in deep
RL range) — all with pure Python code, zero neural network training.

### 2.2 The Gap in Academic Literature Tools

HL has been demonstrated on games and control tasks.  We argue it is
equally applicable — and arguably more impactful — when applied to
**academic knowledge curation**.  The "environment" becomes the PDF
corpus and user queries; the "feedback" becomes missing facts, user
corrections, and detected contradictions; the "policy" becomes the
extraction pipeline and knowledge graph maintenance rules.

| Dimension | Weng's Atari/MuJoCo HS | Our Domain Expert HS |
|-----------|----------------------|---------------------|
| Environment | Game engine, physics sim | PDF corpus, user queries |
| Feedback | Reward signal, video replay | Missing facts, user corrections, contradiction detection |
| Policy | Heuristic strategy code | Extraction pipeline + fact verification rules |
| State | Game variables | Knowledge graph: claims, evidence spans, relations |
| Memory | trials.jsonl, summary.csv | Vector DB, fact DB, versioned claim history |
| Regression test | Fixed-seed replay | Query consistency checks |

---

## 3. Approach

### 3.1 System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Domain Expert System                         │
│                                                                  │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│   │   Ingest     │───→│   Extract    │───→│   Query      │←──User
│   │   (Absorb)   │    │   Facts      │    │   Interface  │      │
│   └──────────────┘    └──────────────┘    └──────────────┘      │
│         ↑                                                  │     │
│    New papers                                        NL queries  │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Knowledge Base (per-topic)                               │  │
│   │                                                           │  │
│   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │  │
│   │  │ Full-text   │  │ Structured  │  │ Claim       │       │  │
│   │  │ Chunks      │  │ Facts       │  │ Graph       │       │  │
│   │  │ (vector)    │  │ (SQL+JSON)  │  │ (relations) │       │  │
│   │  └─────────────┘  └─────────────┘  └─────────────┘       │  │
│   │                        │                                   │  │
│   │                  ┌─────────────┐                           │  │
│   │                  │ Versioned   │                           │  │
│   │                  │ History     │                           │  │
│   │                  │ (superseded │                           │  │
│   │                  │  preserved) │                           │  │
│   │                  └─────────────┘                           │  │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Maintenance Loop (Heuristic Learning)                     │  │
│   │                                                           │  │
│   │  Absorb ──→ New paper → extract → compare →               │  │
│   │              NEW / UPDATE / CONFIRM / CONFLICT             │  │
│   │                                                           │  │
│   │  Compress ──→ Periodically: cluster claims,               │  │
│   │                merge evidence, archive superseded          │  │
│   │                                                           │  │
│   │  Verify ──→ Regression-test: re-ask old questions,        │  │
│   │               check answer consistency                     │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Layer 1: Knowledge Ingestion (Absorb Feedback)

**PDF Processing Pipeline:**

```
PDF file
  ↓  marker-pdf / pdfplumber (section-aware parsing)
Section-annotated text blocks
  ↓  semantic chunking (recursive character split + section boundary merge)
Chunks (500-1000 tokens each)
  ↓  embedding (text-embedding-3-small / DeepSeek embedding)
Vector store (LanceDB, per-topic collection)
  ↓  LLM extraction (DeepSeek, structured JSON schema)
Structured facts + evidence spans
```

**Structured Extraction Schema (per-topic configurable):**

```yaml
fact_types:
  method_claim:
    fields: [method_name, task, dataset, metric, score, evidence_span]
  comparison:
    fields: [method_a, method_b, benchmark, result, direction, evidence_span]
  limitation:
    fields: [limitation_text, category, evidence_span]
  contradiction:
    fields: [claim_a, claim_b, paper_a, paper_b, nature, evidence_span]
```

### 3.3 Layer 2: Knowledge Synthesis (Query Engine)

```
User query ("Does Method X outperform Method Y on ImageNet?")
  ↓  embedding → vector search
Top-k chunks across papers (k=20, diversity-reranked)
  ↓  structured fact lookup (SQL: method= X AND method= Y AND dataset=ImageNet)
Hybrid context: chunks + structured facts + claim graph neighbors
  ↓  LLM multi-document synthesis (DeepSeek-Reasoner / GPT-4)
Answer with inline citations + evidence list
```

**Supported query types:**

| Query Type | Example | Mechanism |
|-----------|---------|-----------|
| Factual lookup | "What dataset does BERT use?" | Vector + structured fact retrieval |
| Comparison | "BERT vs RoBERTa on GLUE?" | Dual retrieval + structured comparison |
| Trend | "How has ImageNet top-1 improved 2023-2025?" | Temporal aggregation of metric claims |
| Contradiction | "Any papers disagree with dropout is essential?" | Claim similarity + negation detection |
| Evidence strength | "How many papers independently verify X?" | Claim graph in-degree |
| Gap analysis | "What architectures haven't been tried on task Y?" | Taxonomy coverage minus extracted claims |

### 3.4 Layer 3: Self-Growing Knowledge (Maintenance)

**Absorb — triggered by each new paper:**

```
New paper ingested
  ↓  extract structured facts
  ↓  compare each fact against existing KB
  ↓  classify:
      ├─ NEW: previously unseen method/dataset/claim → add
      ├─ UPDATE: improves SOTA on existing benchmark → add, mark old as superseded
      ├─ CONFIRM: replicates existing finding → add, increment evidence count
      └─ CONFLICT: contradicts existing claim → add, flag for user attention
```

**Compress — triggered periodically or by user:**

```
Trigger: KB facts exceed threshold, or user requests synthesis
  ↓  Cluster semantically similar claims across papers
  ↓  Merge redundant evidence chains into single consensus entry
  ↓  Identify stale/contradicted claims → mark as superseded, preserve in history
  ↓  Generate "consensus snapshot": current best-evidence claims per topic
```

### 3.5 Case Study: Enrichment Strategy Discovery via HL

Before formalizing the Domain Expert architecture, we already practiced
Heuristic Learning to solve a concrete sub-problem: **abstract
enrichment across heterogeneous academic venues.**

```
Phase 1: Probe environment
  → Tested 31 venue+year combos, 10 papers each
  → Priority: S2 API → arXiv API → OpenReview API → venue fetcher

Phase 2: Read failure logs (Absorb feedback)
  → USS (USENIX Security): S2 covers only 3-10%
  → TOSEM 2023: S2 covers only 50%
  → CHI, FSE, UIST, ISSTA: S2 covers 90-100%

Phase 3: Agent modifies code (Code update)
  → Wrote strategies/usenix.py: fetch_usenix_abstract() via httpx
  → Wrote strategies/crossref.py: fetch_crossref_abstract() via DOI API
  → Refactored sources.py: venue-optimized source selection table

Phase 4: Verify improvement
  → TOSEM 2023: 50% → 99% coverage (107/108 papers)
  → USS 2025: 60% S2 + 40% venue fallback = 100%

Phase 5: Compress history
  → Consolidated 31 probe results into _VENUE_SOURCES dict:
    Tier 1 (S2 dominates): CHI, FSE, ISSTA, UIST, NAACL, NeurIPS, EMNLP
    Tier 2 (S2 + OpenReview): ICML, ACL, CCS, COLM, AAAI
    Tier 3 (Venue fetcher primary): USS
  → Documented in devdocs/venue-enrich-strategies.md as regression artifact
```

This microcosm demonstrates all five phases of our proposed Domain
Expert: probe → absorb → modify → verify → compress.  The same
feedback loop now scales to full-text knowledge extraction.

---

## 4. Evaluation Plan

> **Note:** This section outlines the planned evaluation.  Automated
> benchmarks and user study have not yet been executed.  RQ design
> follows the structure of TradeSweep (Lee et al., ICSE 2025) [2].

### 4.1 Research Questions

TradeSweep [2] structures its RQs along three dimensions — automated
correctness, user efficiency, and usability/trust — a template that
maps directly to our system.  We add two dimensions unique to our HL
framing: longitudinal growth and evidence-provenance trust.

| RQ | Type | Question | TradeSweep [2] analogue |
|----|------|----------|--------------------------|
| **RQ1** | Automated | Can Domain Expert accurately recall and extract key papers and SOTA claims for a given research area? | ~ RQ1 (code correctness) |
| **RQ2** | Automated | What is the precision/recall of structured fact extraction compared to ground truth? | ~ RQ1 (execution success rate) |
| **RQ3** | User study | Does Domain Expert reduce time and cognitive load vs existing tools (GPT-4+search, Semantic Scholar) for literature research tasks? | ~ RQ2 (task time, error rate) |
| **RQ4** | User study | Do users trust Domain Expert answers more due to paragraph-level evidence tracing? What are the SUS and NASA-TLX scores? | ~ RQ3 (Likert satisfaction, SUS) |
| **RQ5** | Longitudinal | Does the KB improve over time as more papers are ingested (validating HL)? Can new papers be correctly classified as NEW/UPDATE/CONFLICT? | Not addressed in TradeSweep |

### 4.2 Automated Evaluation (RQ1, RQ2)

**Dataset:** 3 research areas from crawled venues, each with constructed ground truth:
- Area A: GUI Agents (CHI, UIST)
- Area B: LLM Code Generation (ICSE, FSE)
- Area C: Federated Learning Security (USS, CCS, NDSS)

**Ground truth (per area):**
- Key papers: 30-50 papers annotated by domain experts
- SOTA claims: 20-30 fact triples (method, dataset, metric, score)
- Known contradictions: 5-10 conflicting claim pairs
- Method taxonomy: 3-4 level hierarchy

**RQ1 Metrics (Recall & Coverage):**

| Metric | Definition | Target |
|--------|-----------|--------|
| Paper recall@k | % of expert-annotated papers found in KB (k=10,20,50) | ≥ 80% |
| Claim extraction recall | % of ground-truth claims successfully extracted | ≥ 70% |
| Taxonomy coverage | % of taxonomy categories with ≥3 papers | ≥ 90% |

**RQ2 Metrics (Accuracy):**

| Metric | Definition | Target |
|--------|-----------|--------|
| Claim precision | % of extracted claims verified correct by human judge | ≥ 85% |
| Evidence accuracy | % of claims with correct evidence span (source paragraph) | ≥ 80% |
| Answer quality | LLM-as-judge (GPT-4 blind), Likert 1-5 | ≥ 3.5 |
| Contradiction recall | % of ground-truth contradictions detected | ≥ 60% |
| Hallucination rate | % of synthesized claims not traceable to KB | ≤ 10% |

### 4.3 User Study (RQ3, RQ4)

**Participants:** 12-20 researchers (PhD students, postdocs) in SE/AI/ML
(TradeSweep [2] used 32; 12-20 is acceptable for an ICSE Tool Demo)

**Design:** Within-subjects, counterbalanced order

**Tasks (5 per condition, 30 min total):**
1. Factual lookup: "What is the best reported accuracy on task X?"
2. Comparison: "Compare method A and B — which is better, by how much?"
3. Dataset survey: "What datasets are commonly used for task Y, and how large?"
4. Limitation analysis: "What are the known limitations of approach Z?"
5. Contradiction check: "Do any papers disagree with claim W?"

**Conditions (3):**
| Condition | Tool | Notes |
|-----------|------|-------|
| **Baseline 1** | Google Scholar + ChatGPT (web search) | Current common practice |
| **Baseline 2** | Semantic Scholar + manual notes | Academic search + human notes |
| **Treatment** | Domain Expert | Our system |

**RQ3 Metrics (Efficiency):**

| Metric | Measurement |
|--------|-------------|
| Task completion time | Per-task timing |
| Answer correctness | Blind expert grading (1-5), following TradeSweep [2] |
| Source traceability | % of answer claims with verifiable citations |

**RQ4 Metrics (Trust & Usability):**

| Metric | Instrument | Reference |
|--------|-----------|-----------|
| System Usability Scale (SUS) | Standard 10-item questionnaire | TradeSweep [2] |
| NASA-TLX | 6-dimension cognitive load | TradeSweep [2] |
| Trust in answer | Likert 1-5: "I am confident this answer is correct" | Ours (new) |
| Evidence utility | Likert 1-5: "Tracing to source paragraphs is helpful" | Ours (new) |
| "Would you use this in your own research?" | Yes/No + free-text rationale | TradeSweep [2] |

### 4.4 Longitudinal Pilot (RQ5)

Deploy 1 active topic for 3 months:

| Tracked Metric | Description |
|---------------|-------------|
| Papers ingested | Cumulative new paper count |
| KB facts count | Total structured facts in KB |
| Claim graph density | Avg cross-paper relations per paper |
| Update accuracy | % of new papers correctly classified (NEW/UPDATE/CONFLICT) |
| Answer quality over time | Same queries at different KB sizes |
| KB staleness | Median time from paper publication to KB update |
| Compression events | Trigger count + KB size before/after compress |

**HL hypothesis verification:** Scatter plot of answer quality vs KB age,
expecting positive correlation.

### 4.5 Qualitative Analysis

Following TradeSweep [2]'s failure analysis approach:

- **Success cases:** 3-5 exemplar queries with evidence traces and synthesis steps
- **Failure mode taxonomy:** Root-cause classification (missing paper, extraction
  error, synthesis error, missed contradiction)
- **User feedback themes:** Thematic coding of free-text responses
- **Compression before/after:** Illustrative case of one compress cycle

### 4.6 Structural Comparison with TradeSweep [2] Evaluation

| Dimension | TradeSweep [2] | Domain Expert |
|-----------|---------------|---------------|
| Automated tasks | 30 preprocessing tasks | 3 areas × 20-30 claims = 60-90 verification points |
| User study N | 32 participants | 12-20 (acceptable for tool demo) |
| Baselines | 3 (GPT-4o, Data Wrangler, Code Interpreter) | 3 (GPT-4+search, S2+manual, static survey) |
| Measured dimensions | Correctness, time, error rate, SUS, Likert | Above + source traceability + trust + longitudinal |
| Unique dimensions | Code library growth | Evidence provenance, contradiction detection, HL growth |
| Longitudinal | Not addressed (single-session) | 3-month pilot (core novelty contribution) |

---

## 5. Related Work

### 5.1 Heuristic Learning

Weng (2026) proposed Heuristic Learning as a new paradigm where coding
agents maintain growing Heuristic Systems through code evolution rather
than gradient descent.  Results on Atari Breakout (864, theoretical
max), MuJoCo Ant (6000+, deep RL range), and Atari57 (median HNS
surpassing PPO) demonstrate the paradigm's viability on game-playing
and control tasks.  Our work is the first to apply HL to **knowledge
work** — a domain with richer feedback modalities (user corrections,
contradiction detection, staleness marking) and stronger requirements
for compression (preventing knowledge graph bloat).

### 5.2 LLM-Assisted Literature Review

**RAG-based tools** (Elicit, Consensus, PaperQA2) use retrieval-augmented
generation to answer questions over academic papers, but operate in a
single-session, stateless paradigm — no persistent knowledge accumulates.

**Systematic review tools** (ASReview, Colandr, Rayyan) use active
learning to accelerate paper screening, but stop at the screening
phase — no extraction, synthesis, or cross-paper reasoning.

**LLM survey generation** (our own survey_agent, and similar systems)
produce structured survey reports from crawled papers, but treat the
report as the end product — knowledge is discarded after generation.

### 5.3 LLM Tool Papers at SE Venues

TradeSweep (Lee et al., ICSE 2025 Tool Demo) demonstrated that a
well-engineered LLM-based tool with dual evaluation (automated +
user study) is publishable at top SE venues.  Their system retrieves
code templates for spreadsheet preprocessing; ours retrieves
structured facts for literature synthesis.  The architectural pattern
— RAG + LLM generation + human feedback loop — is shared, but our
system adds persistence, self-growth, and a novel HL framing.

### 5.4 Knowledge Bases and Expert Systems

Classic expert systems (MYCIN, DENDRAL) encoded domain knowledge as
hand-crafted rules — effective but prohibitively expensive to maintain.
Modern knowledge bases (Wikidata, DBPedia) are broad but shallow —
fact triples without evidence provenance or contradiction handling.
Our system combines the depth of expert systems with the scale of LLMs,
using HL to keep maintenance costs tractable.

---

## 6. Conclusion and Future Work

We presented **Domain Expert**, an LLM-maintained Heuristic System for
academic literature that ingests PDF full-text, extracts structured
facts with evidence provenance, and supports cross-paper reasoning
through natural language queries.  Our key contribution is reframing
literature curation as a **Heuristic Learning** problem: the system
improves through code+data co-evolution rather than model retraining,
with explicit Absorb and Compress operations that keep the knowledge
base healthy.

We built on a mature survey_agent pipeline that already crawls 20+
venues and demonstrated HL in microcosm through the discovery of
venue-adaptive enrichment strategies.  The enrichment story — probe 31
combos, absorb failure patterns, modify code, verify improvement,
compress into a strategy table — is a concrete instantiation of the
same learning loop we now scale to full-text knowledge extraction.

**Future work:**
- Complete the evaluation (automated benchmarks + user study)
- Implement the compression pipeline (claim clustering, evidence merging)
- Explore cross-topic knowledge transfer (knowledge learned for one
  research area informing another)
- Investigate how the HL maintenance loop can be made more autonomous,
  reducing the need for human-initiated compression cycles

---

## References

[1] Weng, J. (2026). *Learning Beyond Gradients.*
    https://trinkle23897.github.io/learning-beyond-gradients/

[2] Lee, C.-T., Neeser, A., Xu, S., Katyan, J., Cross, P., Pathakota, S.,
    Norman, M., Simeone, J., Chandrasekaran, J., & Ramakrishnan, N. (2025).
    Can an LLM Find Its Way around a Spreadsheet? In *Proceedings of the
    IEEE/ACM 47th International Conference on Software Engineering (ICSE '25)*,
    pp. 294–306. IEEE Press. DOI: 10.1109/ICSE55347.2025.00101
