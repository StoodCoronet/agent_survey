# agent-survey

Crawl AI-agent papers (esp. computer-use / GUI agent) from SE / Security / AI venues (2023–now), classify them with DeepSeek, and produce an Obsidian-ready survey.

See [PLAN.md](./PLAN.md) for the full design.

## Setup

```bash
conda activate agent_survey         # python 3.12 env
uv pip install -e .

cp .env.example .env                 # then fill DEEPSEEK_API_KEY
```

## Pipeline (each stage is resumable + prints stats)

```bash
agent-survey harvest           # DBLP listings (all venues × years)
agent-survey enrich            # S2/arXiv → abstract + arxiv_id + pdf_url
agent-survey search-recall     # S2/arXiv keyword search → flip prefilter_hit
agent-survey prefilter         # local keyword regex over title+abstract
agent-survey stats             # inspect DB breakdown, decide whether to continue
agent-survey classify          # DeepSeek-Flash: relevance + domain + method tags
agent-survey fulltext          # download arXiv PDFs for classified papers
agent-survey deepdive          # DeepSeek-Pro: structured extraction on full text
agent-survey report            # Obsidian vault + survey.md + JSON
```

Or: `bash scripts/run_all.sh` — pauses before paid stages.

## Outputs

- `output/db/papers.sqlite` — single source of truth
- `output/json/papers.json` + `taxonomy.json`
- `output/markdown/survey.md` + `classification_table.md`
- `output/obsidian/` — vault with per-paper notes + index MOC + per-domain tags
- `output/stats/{stage}_{ts}.json` — per-stage checkpoint stats
- `cache/llm/…` (+ SQLite `llm_calls` table) — LLM response cache keyed by input hash
