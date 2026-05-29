# Agent Survey — Technical Specification

> **Version**: 2026-05-28
> **Purpose**: Complete technical reference for reproducing, modularizing, and eventually skill-izing the Agent Survey pipeline.

---

## 1. Overview

Agent Survey is an end-to-end automated pipeline for surveying academic literature in a specific domain (AI Agents). It crawls papers from top-tier venues, enriches metadata, classifies relevance, builds a multi-dimensional taxonomy, and generates a bilingual static documentation site.

### Key Design Principles

- **Incremental & resumable**: Every stage writes to SQLite; re-running skips already-done work.
- **LLM-cached**: All LLM calls are cached by `input_hash` (stage + model + prompt_version + messages). Re-running costs $0 for cached responses.
- **Venue-aware**: Classification and selection prioritize venue tiers (SE/Security > AI > NLP > HCI).
- **Bilingual**: All generated descriptions and summaries are in English + Chinese.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI / TUI Layer                           │
│  Typer CLI (agent-survey <cmd>) + Interactive TUI                │
├─────────────────────────────────────────────────────────────────┤
│                        Stage Layer (s00-s11)                     │
│  12 sequential stages, each self-contained, idempotent           │
├─────────────────────────────────────────────────────────────────┤
│                      Analysis Layer                              │
│  Stats, cost estimation, coverage reports                        │
├─────────────────────────────────────────────────────────────────┤
│                      Service Layer                               │
│  LLM (DeepSeek), PDF extraction, Web scraping (Playwright)       │
├─────────────────────────────────────────────────────────────────┤
│                        Core Layer                                │
│  Config (Pydantic), DB (SQLite WAL), Console (Rich logging)      │
└─────────────────────────────────────────────────────────────────┘
```

### Directory Layout

```
agent_survey/
├── config.yaml              # Central configuration
├── src/agent_survey/
│   ├── core/                # config, db, console
│   ├── services/            # llm, pdf_extract, arxiv, web_scrape
│   ├── stages/              # s00_harvest ~ s11_summary
│   ├── analysis/            # stats, cost estimation, coverage
│   ├── report/              # markdown, obsidian export
│   ├── cli.py               # Typer CLI entry
│   └── tui.py               # Interactive terminal UI
├── scripts/
│   └── generate_docs.py     # Static site generator
├── docs/                    # Generated static site
└── output/
    ├── db/papers.sqlite     # Main database
    ├── pdfs/                # Downloaded PDFs
    ├── logs/                # Execution logs
    └── stats/               # Per-stage JSON stats
```

---

## 3. Data Model

### 3.1 Main Table: `papers`

| Column | Type | Description |
|--------|------|-------------|
| `paper_id` | TEXT PK | Stable ID (dblp_key or hash) |
| `dblp_key` | TEXT UNIQUE | DBLP record key |
| `arxiv_id` | TEXT | arXiv ID if available |
| `doi` | TEXT | DOI |
| `title` | TEXT NOT NULL | Full title |
| `abstract` | TEXT | Abstract (enriched from arXiv/S2/OpenReview) |
| `venue` | TEXT | Venue short name (e.g. "ICSE") |
| `venue_area` | TEXT | Research area (SE, Security, AI, NLP, HCI) |
| `venue_type` | TEXT | "conference" or "journal" |
| `year` | INTEGER | Publication year |
| `authors_json` | TEXT | JSON list of authors |
| `url` | TEXT | Paper landing page URL |
| `pdf_url` | TEXT | Direct PDF URL |
| `pdf_path` | TEXT | Local PDF path (after s04_fulltext) |
| `code_url` | TEXT | Code repository URL |
| `tldr` | TEXT | One-line TL;DR |
| `prefilter_hit` | TEXT | JSON list of matched keyword categories |
| `relevance` | TEXT | core / related / adjacent / irrelevant |
| `domain_primary` | TEXT | Primary research domain |
| `domain_secondary_json` | TEXT | Secondary domains |
| `method_tags_json` | TEXT | Method tags |
| `deepdive_json` | TEXT | Structured extraction from PDF (s05) |
| `topics_json` | TEXT | Topic classifications (s06) |
| `sub_topics_json` | TEXT | Sub-topic + dedup results (s06b) |
| `taxonomy_json` | TEXT | Multi-dimensional taxonomy paths (s07) |
| `citation_json` | TEXT | Citation graph data (s08) |
| `short_title` | TEXT | Abbreviated title (s09) |
| `summary_en` | TEXT | 3-4 sentence English summary (s11) |
| `summary_zh` | TEXT | 3-4 sentence Chinese summary (s11) |
| `stage_status_json` | TEXT | Per-paper stage completion tracking |
| `created_at` / `updated_at` | TEXT | ISO timestamps |

### 3.2 Cache Table: `llm_calls`

| Column | Description |
|--------|-------------|
| `input_hash` | SHA256 of (stage + model + prompt_version + messages) |
| `response_json` | Full LLM response (parsed JSON) |
| `paper_id` | Associated paper (or synthetic ID for non-paper calls) |

### 3.3 Checkpoint Table: `harvest_runs`

Tracks per-venue per-year crawl status (`done` | `failed` | `empty`).

### 3.4 Taxonomy Table: `taxonomy_descriptions`

| Column | Description |
|--------|-------------|
| `tree_name` | Dimension name (e.g. `application_domain`) |
| `path` | Category path (e.g. `web-agent/web-navigation`) |
| `desc_en` / `desc_zh` | Bilingual category description |
| `metadata_json` | `{methods, datasets, trends}` |
| `status` | `pending` / `processing` / `done` / `failed` |

---

## 4. Pipeline Stages

### Stage 0: Harvest (`s00_harvest`)

**Input**: `config.yaml` → venue list + year range
**Output**: Raw paper records in `papers` table (title, venue, year, authors, url)

- Fetches DBLP listings for every `(venue, year)` combination.
- Supports special fetching modes:
  - `toc_stream`: For venues with broken DBLP index (e.g. USENIX Security)
  - `journal_stream` + `journal_volumes`: For journals without per-year index
  - `json_source_url`: For external sources (e.g. COLM mini-conf)
- Filters out co-located workshops by `key_prefixes`.
- Checkpointed via `harvest_runs` table.

**CLI**: `agent-survey harvest [--force] [--workers N]`

### Stage 0b: Search Recall (`s00b_search_recall`)

**Input**: Semantic Scholar + arXiv search queries
**Output**: Additional papers matched back to DBLP entries

- Searches S2/arXiv for domain-specific queries (e.g. "GUI agent").
- Fuzzy-matches results against existing DBLP titles.
- Flips `prefilter_hit` for matched papers so they enter classification.

**CLI**: `agent-survey search-recall [--per-query 200]`

### Stage 1: Enrich (`s01_enrich`)

**Input**: Papers without abstracts
**Output**: Filled `abstract`, `arxiv_id`, `pdf_url`, `doi`, `tldr`

- Tries sources in order: **arXiv** → **Semantic Scholar** → **OpenReview**.
- Uses title fuzzy matching to find the right paper on each platform.
- `s01_enrich_web.py`: Fallback for failed papers using Playwright + arXiv web scraping.

**CLI**: `agent-survey enrich [--force] [--workers N]`

### Stage 2: Prefilter (`s02_prefilter`)

**Input**: All papers
**Output**: `prefilter_hit` JSON (matched keyword categories)

Logic (case-insensitive regex on title + abstract):
```
INCLUDE if:
  agent_core matches
  OR (agent_generic matches AND (se_context matches OR sec_context matches))
```

**CLI**: `agent-survey prefilter`

### Stage 3: Classify (`s03_classify`)

**Input**: Papers (prefilter hits or all)
**Output**: `relevance` (core / related / adjacent / irrelevant), `domain_primary`, `domain_secondary_json`, `method_tags_json`

- Venue-aware batch classification via DeepSeek Flash.
- Batched 20 papers per LLM call for cost efficiency.
- `--prefilter-only` mode: only classify keyword hits (~$0.2 vs ~$6-7).

**CLI**: `agent-survey classify [--prefilter-only] [--workers N]`

### Stage 4: Fulltext Download (`s04_fulltext`)

**Input**: Core/related/adjacent papers with arXiv IDs
**Output**: `pdf_path` (local file)

- Downloads arXiv PDFs concurrently.
- Skips already-downloaded files.

**CLI**: `agent-survey fulltext [--workers N]`

### Stage 5: Deepdive (`s05_deepdive`)

**Input**: Core papers with PDFs
**Output**: `deepdive_json` (structured extraction)

- Uses DeepSeek Pro (reasoner) for high-quality extraction.
- Extracts: contribution type, problem, method, key results, limitations.

**CLI**: `agent-survey deepdive [--workers N]`

### Stage 6: Topic Classification (`s06_topics`)

**Input**: Core papers
**Output**: `topics_json` (multi-label topic IDs with scores)

- Incremental topic discovery: LLM can suggest new topics not in the existing list.
- Each paper gets multiple topic labels with confidence scores.

**CLI**: `agent-survey classify-topics [--workers N]`

### Stage 6b: Sub-topic Dedup (`s06b_subtopic_dedup`)

**Input**: Papers per topic
**Output**: `sub_topics_json` (discovered sub-topics + dedup flags)

Two-phase LLM pipeline per topic:
1. **Discover**: Find sub-topics within a batch of 20-25 papers.
2. **Dedup**: Identify near-duplicate papers within each sub-topic group.

**CLI**: `agent-survey dedup [--scope core|related|adjacent]`

### Stage 7: Taxonomy (`s07_taxonomy`)

**Input**: Core papers
**Output**: `taxonomy_json` (multi-dimensional leaf paths)

Maps each paper to 3 independent trees:
1. `application_domain` — what the agent does (web, mobile, desktop, etc.)
2. `technical_approach` — how it works (planning, memory, tool-use, etc.)
3. `research_goal` — why it exists (framework, benchmark, attack, defense, etc.)

**CLI**: `agent-survey taxonomy [--workers N]`

### Stage 8: Citation (`s08_citation`)

**Input**: Core papers with PDFs
**Output**: `citation_json` (in-degree, out-degree, cited paper IDs)

- Extracts reference sections from PDFs.
- Fuzzy-matches against known core paper titles.
- Generates `docs/citation_graph.html` (D3.js force-directed graph).

**CLI**: `agent-survey citation [--scope core|related|adjacent]`

### Stage 9: Short Titles (`s09_short_titles`)

**Input**: Core papers
**Output**: `short_title`

- Generates concise abbreviations (≤35 chars) for long titles.
- Uses PDF excerpts for context to ensure distinctiveness.
- Deduplicates collisions across the entire corpus.

**CLI**: `agent-survey short-titles [--scope core|related|adjacent] [--workers N]`

### Stage 10: Category Descriptions (`s10_category_desc`)

**Input**: Taxonomy + papers
**Output**: `taxonomy_descriptions` table (bilingual descriptions + metadata)

Two-phase strategy per category:
- **Stage A (Abstract Selection)**: From ALL papers in category, LLM selects up to 20 representative papers (diverse, top-venue, recent).
- **Stage B (PDF-based Generation)**: Reads PDF excerpts of selected papers, generates:
  - `desc_en` / `desc_zh`: 3-4 sentence overview
  - `metadata_json`: `{methods, datasets, trends}`

Level-aware prompts:
- Level 1 (sub-category): Plain-language overview of the sub-field
- Level 2+ (leaf): Concrete techniques & challenges

**CLI**: `agent-survey category-desc [--force] [--workers N]`

### Stage 11: Paper Summaries (`s11_summary`)

**Input**: Core papers (title + abstract)
**Output**: `summary_en` / `summary_zh`

- 3-4 sentence bilingual summary per paper.
- Uses DeepSeek Flash (fast, cheap).
- Abstract-only (no PDF needed).

**CLI**: `agent-survey summary [--force] [--workers N]`

---

## 5. Static Site Generation

**Script**: `scripts/generate_docs.py`
**Output**: `docs/` directory

### Generated Pages

| Page | Description |
|------|-------------|
| `index.html` | Overview dashboard with key stats |
| `taxonomy.html` | Interactive taxonomy explorer (left tree, center detail, right paper list) |
| `mindmap.html` | D3.js butterfly mindmap with fold/unfold and paper cards |
| `papers.html` | Searchable paper list with tags and summaries |
| `citation_graph.html` | Force-directed citation network |
| `data.json` | All data exported as single JSON (consumed by all pages) |

### Data Flow

```
papers.sqlite
    → generate_docs.py
        → data.json (papers + taxonomy_desc + tree_hierarchy + edges)
        → index.html, taxonomy.html, mindmap.html, papers.html, citation_graph.html
```

---

## 6. Configuration System

`config.yaml` is the single source of truth. Loaded by `core/config.py` into Pydantic models.

### Key Sections

- `years`: `{start, end}` — publication year range
- `venues.conferences` / `venues.journals`: Venue definitions with special fetch modes
- `keywords`: 4 categories (`agent_core`, `agent_generic`, `se_context`, `sec_context`)
- `llm`: Per-stage model settings (model, temperature, max_tokens, prompt_version)
- `paths`: Output directory layout
- `network`: Concurrency and timeout settings

### Environment Variables

| Variable | Used For |
|----------|----------|
| `DEEPSEEK_API_KEY` | LLM calls |
| `DEEPSEEK_BASE_URL` | Custom endpoint (default: https://api.deepseek.com) |
| `SEMANTIC_SCHOLAR_API_KEY` | S2 API (optional, higher rate limits) |

---

## 7. Concurrency & Performance

### SQLite Thread Safety

- **WAL mode** enabled (`PRAGMA journal_mode=WAL`)
- **Busy timeout** 10s (`PRAGMA busy_timeout=10000`)
- **Pattern**: Main thread passes `db_path: Path` to workers; each worker opens its own `DB(db_path)` connection.

### Worker Scaling

| Stage | Default Workers | Bottleneck |
|-------|----------------|------------|
| Harvest | 4 | Network (DBLP) |
| Enrich | 5 | Network (arXiv/S2) |
| Classify | 5 | LLM API rate limits |
| Fulltext | 5 | Network (arXiv CDN) |
| Deepdive | 3 | LLM API (expensive) |
| Category-desc | 20 | LLM API (cached) |
| Summary | 20 | LLM API (cached) |

### Cost Benchmarks (635 papers, 2026-05)

| Stage | Est. Cost |
|-------|-----------|
| Stage 3 (classify, full) | ~$6-7 |
| Stage 5 (deepdive) | ~$20-30 |
| Stage 10 (category-desc) | ~$5-10 |
| Stage 11 (summary) | ~$0.06 |

---

## 8. Extensibility & Modularization Roadmap

### 8.1 Current Pain Points

1. **Tight coupling to DeepSeek**: `services/llm.py` is hardcoded to DeepSeek/OpenAI-compatible API.
2. **Monolithic stages**: Each stage is a standalone script with duplicated boilerplate (progress bars, stats, CLI registration).
3. **HTML generation in Python strings**: `generate_docs.py` embeds large JS/CSS blocks as Python strings.
4. **No plugin system**: Adding a new venue source or a new classification dimension requires editing core files.

### 8.2 Proposed Skill-ization

```
agent-survey/
├── skills/
│   ├── harvest/           # Venue source plugins
│   ├── enrich/            # Metadata resolver plugins
│   ├── classify/          # Relevance classifier (swappable LLM)
│   ├── taxonomy/          # Taxonomy tree definitions
│   ├── extract/           # PDF text extraction strategies
│   └── report/            # Output format plugins (HTML, LaTeX, Markdown)
```

Each skill implements a standard interface:

```python
class Skill(Protocol):
    name: str
    def run(self, db: DB, cfg: Config, **kwargs) -> dict: ...
    def status(self, db: DB) -> str: ...
```

### 8.3 Future Directions

1. **Multi-LLM backend**: Support Claude, GPT-4, local models via unified interface.
2. **Real-time dashboard**: Replace static HTML with a lightweight web server (FastAPI + React).
3. **Agentic survey**: Let an autonomous agent query the corpus in natural language ("How many web agents use reinforcement learning?").
4. **Cross-survey reuse**: Parameterize venue list + keyword list + taxonomy spec to survey any domain (e.g. "LLM for code generation").

---

## 9. Quick Start (for Code Agents)

### Prerequisites

```bash
# Python 3.12, conda environment
conda create -n agent_survey python=3.12
conda activate agent_survey
pip install -e .

# Required: DeepSeek API key
cp .env.example .env
# Edit .env: DEEPSEEK_API_KEY=sk-...
```

### Full Pipeline Execution

```bash
agent-survey harvest          # Stage 0
agent-survey enrich           # Stage 1
agent-survey prefilter        # Stage 2
agent-survey classify         # Stage 3
agent-survey fulltext         # Stage 4
agent-survey deepdive         # Stage 5
agent-survey classify-topics  # Stage 6
agent-survey dedup --scope core
agent-survey taxonomy         # Stage 7
agent-survey citation --scope core  # Stage 8
agent-survey short-titles --scope core  # Stage 9
agent-survey category-desc --workers 20  # Stage 10
agent-survey summary --workers 20        # Stage 11
agent-survey generate-docs    # Build static site
```

Or use TUI:

```bash
agent-survey tui
```

### Resume After Crash

Every stage is idempotent. Simply re-run the same command.

```bash
# Example: category-desc was interrupted
agent-survey category-desc --workers 20
# Skips already-done nodes automatically
```

---

## 10. File Reference

| File | Purpose |
|------|---------|
| `config.yaml` | All configuration |
| `src/agent_survey/core/db.py` | SQLite schema + migrations |
| `src/agent_survey/core/config.py` | Pydantic config models |
| `src/agent_survey/services/llm.py` | DeepSeek client + caching |
| `src/agent_survey/cli.py` | All CLI commands |
| `src/agent_survey/tui.py` | Interactive UI |
| `scripts/generate_docs.py` | Static site generator |
| `TAXONOMY_SPEC.md` | Taxonomy tree definitions |
