# agent-survey

Crawl AI-agent papers (esp. computer-use / GUI agent) from SE / Security / AI venues (2023–now), classify them with DeepSeek, and produce an Obsidian-ready survey.

See [PLAN.md](./PLAN.md) for the full design.

## Setup

```bash
conda activate survey_agent         # python 3.12 env
uv pip install -e .

cp .env.example .env                 # then fill DEEPSEEK_API_KEY
```

## Pipeline (each stage is resumable + prints stats)

```bash
survey_agent harvest           # DBLP listings (all venues × years)
survey_agent enrich            # S2/arXiv → abstract + arxiv_id + pdf_url
survey_agent search-recall     # S2/arXiv keyword search → flip prefilter_hit
survey_agent prefilter         # local keyword regex over title+abstract
survey_agent stats             # inspect DB breakdown, decide whether to continue
survey_agent classify          # DeepSeek-Flash: relevance + domain + method tags
survey_agent fulltext          # download arXiv PDFs for classified papers
survey_agent deepdive          # DeepSeek-Pro: structured extraction on full text
survey_agent report            # Obsidian vault + survey.md + JSON
```

Or: `bash scripts/run_all.sh` — pauses before paid stages.

## Outputs

- `output/db/papers.sqlite` — single source of truth
- `output/json/papers.json` + `taxonomy.json`
- `output/markdown/survey.md` + `classification_table.md`
- `output/obsidian/` — vault with per-paper notes + index MOC + per-domain tags
- `output/stats/{stage}_{ts}.json` — per-stage checkpoint stats
- `cache/llm/…` (+ SQLite `llm_calls` table) — LLM response cache keyed by input hash
