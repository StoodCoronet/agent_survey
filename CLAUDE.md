# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`survey_agent` crawls academic papers from SE/Security/AI venues, classifies them with DeepSeek, and produces an Obsidian-ready survey. Supports multiple survey topics via per-topic configuration. See `PLAN.md` for the full design, `PLAN_MULTI_TOPIC.md` for the multi-topic refactoring spec.

## Setup

```bash
conda activate survey_agent            # python 3.12
uv pip install -e .
cp .env.example .env                   # then fill DEEPSEEK_API_KEY
python -m playwright install chromium  # for enrich-web
```

## Commands

All pipeline commands accept `--topic` / `-t` to specify the survey topic (default: active topic from config.yaml).

```bash
# Topic management
survey_agent topic list              # list available topics
survey_agent topic show [name]      # show topic config overview
survey_agent topic use <name>        # set active topic in config.yaml
survey_agent topic new <name>        # create new topic scaffold

# Pipeline (each stage resumable, --topic <name> to select topic)
survey_agent harvest                 # DBLP listings (venue × year)
survey_agent search-recall           # S2/arXiv keyword search → flip prefilter_hit
survey_agent enrich                  # S2/arXiv/OpenReview → abstract + arxiv_id
survey_agent enrich-web              # Playwright fallback for failed abstracts
survey_agent prefilter               # topic-specific keyword regex filter
survey_agent stats                   # DB overview (topic-aware)
survey_agent classify                # DeepSeek-Flash batch classification (per-topic prompts)
survey_agent classify-topics         # incremental multi-label topic classification
survey_agent dedup                   # sub-topic dedup (3 scopes: core/related/adjacent)
survey_agent taxonomy                # multi-dimensional taxonomy classification (per-topic trees)
survey_agent fulltext                # download arXiv PDFs for classified papers
survey_agent citation                # extract citations from PDFs + build D3 graph
survey_agent deepdive                # DeepSeek-Pro structured extraction (per-topic fields)
survey_agent short-titles            # generate abbreviated titles
survey_agent category-desc           # bilingual taxonomy category descriptions
survey_agent summary                 # bilingual 3-4 sentence paper summaries
survey_agent report                  # Obsidian vault + JSON + Markdown
survey_agent generate-docs           # static docs/ site (per-topic under docs/<topic>/)
survey_agent serve-docs              # serve docs/ at http://localhost:48000
survey_agent tui                     # interactive TUI menu

# Analysis helpers
survey_agent abstract-coverage       # abstract coverage by venue
survey_agent keyword-stats           # keyword hit distribution
survey_agent estimate-cost           # API cost estimate before classify
```

## Multi-topic architecture

Topics are defined in `topics/<name>.yaml`. Each topic has its own:
- **keywords** for prefilter (agent_core / agent_generic / se_context / sec_context)
- **search_queries** for search-recall
- **classify prompts** (system + user templates, relevance levels, domain/method labels)
- **deepdive prompts** (system + user template with extraction fields)
- **taxonomy trees** (3 trees + cross-cutting tags)
- **seed_topics** for stage 6 topic classification

The active topic is set in `config.yaml` (`active_topic: gui-agent`) or via `survey_agent topic use <name>`.

## DB schema

Three key tables for multi-topic:

| Table | Purpose |
|-------|---------|
| `papers` | Paper metadata (title, abstract, venue, year) — topic-independent |
| `paper_topics` | Paper × topic join with per-topic classification results (relevance, domain, taxonomy, short_title, summaries) |
| `topic_deepdive` | Per-topic structured extraction (fields vary by topic) |
| `topics` | Topic registry (name, display_name, active flag) |
| `taxonomy_descriptions` | Per-topic category descriptions (EN/ZH) |

## Architecture

```
src/agent_survey/
├── cli.py              # Typer CLI (~25 subcommands) + topic group
├── tui.py              # Rich interactive TUI with pipeline progress
├── core/
│   ├── config.py       # Config + TopicConfig Pydantic models, topic loading
│   ├── db.py           # SQLite schema, CRUD, paper_topics, topic_deepdive
│   └── console.py      # Rich console + transcript logging
├── services/
│   ├── llm.py          # DeepSeekClient (OpenAI SDK) + cached_chat_json
│   ├── dblp.py         # DBLP JSON/XML harvest
│   ├── s2.py           # Semantic Scholar API
│   ├── arxiv.py        # arXiv API
│   ├── openreview.py   # OpenReview venue data
│   ├── external.py     # Generic HTTP helpers
│   ├── pdf_extract.py  # pdfplumber section-aware extraction
│   ├── taxonomy.py     # TaxonomyManager, seed topics, tree definitions
│   ├── citation_extract.py
│   └── _curl_fallback.py
├── stages/             # Pipeline stages s00-s11
│   ├── s00_harvest.py, s00b_search_recall.py
│   ├── s01_enrich.py, s01_enrich_web.py
│   ├── s02_prefilter.py, s03_classify.py
│   ├── s04_fulltext.py, s05_deepdive.py
│   ├── s06_topics.py, s06b_subtopic_dedup.py
│   ├── s07_taxonomy.py, s08_citation.py
│   ├── s09_short_titles.py, s10_category_desc.py, s11_summary.py
├── analysis/           # stats, cost estimation, keyword analysis
├── report/             # obsidian.py, markdown.py
└── __init__.py
```

## Key design decisions

- **Multi-topic**: Shared pipeline code, per-topic `topics/<name>.yaml` configs. Papers can belong to multiple topics with independent classification results.
- **SQLite is the single source of truth** — Paper IDs are DBLP keys or arXiv IDs with DOI fallback.
- **Stage resumability** — `stage_status_json` tracks per-topic stage completion. Use `--force` to re-run.
- **LLM caching** — `llm_calls` table keyed by input hash (stage+model+prompt_version+messages). Cache hits skip the API call.
- **DeepSeek models**: `deepseek-chat` (Flash) for classification/summaries; `deepseek-reasoner` (Pro, thinking mode) for deepdive and category descriptions.
- **Enrich Playwright fallback** — `enrich-web` scrapes arXiv via Playwright with shared browser across workers.

## Config

- `config.yaml` — global: venues, years, network, active_topic, docs port
- `topics/<name>.yaml` — per-topic: keywords, prompts, taxonomy, search queries
- `.env` — DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, SEMANTIC_SCHOLAR_API_KEY

## Output structure

```
topics/                         # per-topic configs
  gui-agent.yaml
output/
├── db/papers.sqlite            # single source of truth
├── gui-agent/                  # per-topic output
│   ├── json/ markdown/ obsidian/ pdfs/ stats/
├── stats/{stage}_{ts}.json
└── logs/{cmd}_{ts}.log
docs/
├── gui-agent/                  # per-topic static site
│   ├── data.json, index.html, taxonomy.html, mindmap.html,
│   ├── papers.html, citation_graph.html, pdfs/
```
