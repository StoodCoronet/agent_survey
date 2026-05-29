# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`agent-survey` crawls AI-agent papers (especially computer-use / GUI agent) from SE/Security/AI venues (2023--now), classifies them with DeepSeek, and produces an Obsidian-ready survey. See `PLAN.md` for the full design doc, `TAXONOMY_SPEC.md` for the taxonomy system, and `架构重构方案.md` for the architecture refactoring plan.

## Setup

```bash
conda activate survey_agent            # python 3.12
uv pip install -e .
cp .env.example .env                   # then fill DEEPSEEK_API_KEY
```

## Commands

```bash
agent-survey harvest              # DBLP listings (venue × year)
agent-survey search-recall        # S2/arXiv keyword search → flip prefilter_hit
agent-survey enrich               # S2/arXiv/OpenReview → abstract + arxiv_id
agent-survey enrich-web           # Playwright fallback for failed abstracts
agent-survey prefilter            # local keyword regex over title+abstract
agent-survey stats                # DB overview
agent-survey classify             # DeepSeek-Flash batch classification
agent-survey classify-topics      # incremental multi-label topic classification
agent-survey dedup                # sub-topic dedup (3 scopes: core/related/adjacent)
agent-survey taxonomy             # multi-dimensional taxonomy classification
agent-survey fulltext             # download + extract arXiv PDFs
agent-survey citation             # extract citations from PDFs + build graph
agent-survey deepdive             # DeepSeek-Pro structured extraction on full text
agent-survey short-titles         # generate abbreviated titles
agent-survey category-desc        # bilingual taxonomy category descriptions
agent-survey summary              # bilingual 3-4 sentence paper summaries
agent-survey report               # Obsidian vault + JSON + Markdown
agent-survey generate-docs        # static docs/ site from DB data
agent-survey tui                  # interactive TUI menu

# Analysis helpers
agent-survey abstract-coverage    # abstract coverage by venue
agent-survey keyword-stats        # keyword hit distribution
agent-survey estimate-cost        # API cost estimate before classify
```

Every stage is independently resumable — it skips papers already marked `done` in `stage_status_json`. LLM calls are cached by input hash (keyed on `stage + model + prompt_version + messages`), so re-runs don't re-spend.

## Architecture

```
src/agent_survey/
├── cli.py              # Typer CLI (~20 subcommands), each decorated with logfile capture
├── tui.py              # Rich interactive TUI with pipeline progress
├── core/
│   ├── config.py       # Pydantic models for config.yaml + dotenv loading
│   ├── db.py           # SQLite schema, CRUD, LLM cache, harvest checkpoints
│   └── console.py      # Rich console + transcript logging
├── services/
│   ├── llm.py          # DeepSeekClient (OpenAI SDK) + cached_chat_json + prompt templates
│   ├── dblp.py         # DBLP JSON/XML harvest
│   ├── s2.py           # Semantic Scholar API
│   ├── arxiv.py        # arXiv API
│   ├── openreview.py   # OpenReview venue data
│   ├── external.py     # Generic HTTP helpers
│   ├── pdf_extract.py  # pdfplumber section-aware extraction
│   ├── taxonomy.py     # 3-tree taxonomy + seed topics + TaxonomyManager
│   ├── citation_extract.py
│   └── _curl_fallback.py
├── stages/             # Pipeline stages s00-s11, each called by cli.py
│   ├── s00_harvest.py
│   ├── s00b_search_recall.py
│   ├── s01_enrich.py
│   ├── s01_enrich_web.py       # Playwright-based arXiv scraping
│   ├── s02_prefilter.py
│   ├── s03_classify.py         # batch + concurrent LLM classification
│   ├── s04_fulltext.py
│   ├── s05_deepdive.py
│   ├── s06_topics.py
│   ├── s06b_subtopic_dedup.py
│   ├── s07_taxonomy.py
│   ├── s08_citation.py
│   ├── s09_short_titles.py
│   ├── s10_category_desc.py
│   └── s11_summary.py
├── analysis/           # stats, cost estimation, keyword analysis
├── report/             # obsidian.py (vault writer), markdown.py (survey renderer)
└── __init__.py
```

### Key design decisions

- **SQLite is the single source of truth** — `papers` table holds everything from harvest through deepdive. All stages read/write the same DB. Paper IDs are DBLP keys or arXiv IDs, with DOI fallback.
- **Stage resumability** — each stage checks `stage_status_json` (a JSON map `{stage: "done"|"skipped"|...}`) and only processes papers not yet marked done. Use `--force` to re-run.
- **LLM caching** — `llm_calls` table keyed by `input_hash` (SHA256 of stage+model+prompt_version+messages). Cache hits skip the API call entirely.
- **DeepSeek models**: `deepseek-chat` (V4-Flash, non-thinking) for classification/summaries; `deepseek-reasoner` (V4-Pro, thinking mode) for deepdive and category descriptions.
- **Pipeline has two entry branches**: (A) DBLP full harvest by venue+year → enrich → prefilter; (B) S2/arXiv keyword search → reverse-filter by venue. Both merge into the same DB with dedup.
- **Config-driven**: venues, keywords, LLM settings, and paths are all in `config.yaml`. The `Config` Pydantic model validates at load time.
- **Enrich has a Playwright fallback** (`enrich-web`) for papers where API-based enrichment returns no abstract — it scrapes arXiv abstract pages with a single reusable browser process across workers.

### Taxonomy system

Three independent trees (defined in `services/taxonomy.py`):
1. `application-domain` — where the agent operates (web, mobile, desktop, code, etc.)
2. `technical-approach` — core technique (planning, learning, tool-use, multi-agent, etc.)
3. `research-goal` — what the paper studies (benchmark, attack, defense, framework, etc.)

Plus cross-cutting tags: performance, testing-verification, attack-vulnerability, defense-mitigation, benchmark-evaluation.

Category descriptions (bilingual EN/ZH) are generated in stage 10 and stored in the `taxonomy_descriptions` table.

### DB schema notes

The `papers` table uses lightweight migrations (try/except ALTER TABLE ADD COLUMN pattern in `db.py`). JSON-serialized columns: `authors_json`, `stage_status_json`, `deepdive_json`, `topics_json`, `taxonomy_json`, `dedup_keep_json`, `citation_json`. The `dedup_keep_json` stores a dict like `{"core": true, "related": false, "adjacent": false}` — each scope is independent.

### Concurrency patterns

- `classify` uses `ThreadPoolExecutor` with batch+split-half fallback: tries a batch LLM call first; on failure, splits the batch in half and recurses; tiny batches (≤3) fall through to single-paper calls.
- `enrich` uses ThreadPoolExecutor workers calling arXiv → S2 → OpenReview in sequence per paper.
- `enrich-web` uses a single Playwright browser shared across worker threads.
- Token/cost tracking is accumulated thread-locally then merged with a `Lock`.

### Output structure

```
output/
├── db/papers.sqlite          # single source of truth
├── json/papers.json + taxonomy.json
├── markdown/survey.md + classification_table.md
├── obsidian/                 # vault: index MOC + per-paper notes + per-domain tags
├── pdfs/                     # downloaded arXiv PDFs
├── stats/{stage}_{ts}.json   # per-stage checkpoint stats
└── logs/{cmd}_{ts}.log       # Rich transcript logs
```
