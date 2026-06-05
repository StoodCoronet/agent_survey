# 2026-06-05 Daily Changelog

## 1. Survey Mining — Prompts & Bug Fixes

### New topic configs
- `topics/automated-research.yaml` — added `survey_mining` section (`discovery_system`, `discovery_topic_desc`, `keyword_system`)
- `topics/llm-se-tools.yaml` — added `survey_mining` section

### Stage fixes (`s03_survey_mining`)
- **Fix NameError**: added missing `import time`
- **Fix `papers` undefined bug**: when existing surveys in DB and not `--force`, `papers` was never defined → moved batch processing inside `else` block
- **Fix proxy bypass**: switched `_call_and_log` (self-created OpenAI client, bypassed proxy config) → `DeepSeekClient(cfg, stage_name="survey_mining")` so per-stage proxy works
- **Config tuning**: `batch_size: 5 → 50`, `workers: 100 → 10` (11,264 batches → ~1,126 batches)
- **Diagnostics**: added submit/completion timing logs for debugging hangs

## 2. Proxy Key-Mismatch Bug — Root Cause & Fix

**Symptom**: survey-mining appeared "stuck" — progress bar at `[0/11264]` for >1 min.

**Root cause**: `.env` had `HTTP_PROXY=http://192.168.1.106:7890`. `load_config()` writes this into `cfg.network.http_proxy` when YAML value is `""`.

`config/network.yaml` had:
```yaml
stage_proxies:
  s03_survey_mining: ""   # intent: bypass proxy
```

But `get_proxy("survey_mining")` looked up key `"survey_mining"` — not `"s03_survey_mining"`. Key mismatch → no override found → fell back to `.env` proxy → all API calls went through broken proxy → connection errors → retry loops → no batches completed → progress bar frozen.

**Fix**: `get_proxy()` now supports both key styles:
- plain: `"survey_mining"`
- ordered: `"s03_survey_mining"` (fallback pattern `s*_{stage_name}`)

All 13 stages verified returning `None` (bypass) after fix.

## 3. Stage Config File Renaming (Pipeline Order)

`config/stages/` files renamed with `sNN_` prefix so filesystem order matches pipeline order:
```
enrich.yaml           → s02_enrich.yaml
survey_mining.yaml    → s03_survey_mining.yaml
classify.yaml         → s05_classify.yaml
taxonomy.yaml         → s06_taxonomy.yaml
```

- `load_stage_config()` updated to match `s*_{stage_name}.yaml` pattern
- Legacy fallback paths in `src/` stage dirs deleted
- `sources.py` (enrich) updated to use `load_stage_config("enrich")`

## 4. Prefilter Cleanup

Deleted the legacy standalone `prefilter` stage from CLI:
- Removed `@app.command("prefilter")` / `prefilter_legacy()`
- Removed classify `--prefilter-only` option
- Removed `only_prefilter_hits` param from `s05_classify.run()`
- Removed prefilter-hit filtering logic from classify (now classifies ALL papers)
- Renamed `s_prefilter` import → `s_keywords_filter`
- Updated TUI display text: "Prefilter" → "Keywords Filter"
- Removed "If only prefilter hits" cost estimate from `estimate_cost.py`

DB field `prefilter_hit` kept unchanged (migration not worth it).

## 5. Config Split (`config.yaml` → `config/`)

- `config.yaml` deleted, split into:
  - `config/base.yaml` (api_keys, paths, active_topic, docs)
  - `config/venues.yaml`
  - `config/keywords.yaml`
  - `config/network.yaml`
  - `config/llm.yaml`
  - `config/stages/*.yaml`

- `load_config()` merges all `.yaml` under `config/` recursively
- `topic_use()` and TUI topic-switch now write `active_topic` to `config/base.yaml` (not deleted `config.yaml`)

## 6. TUI Fixes

- Fixed `FileNotFoundError` when selecting topic (was reading deleted `config.yaml`)
- Removed `deep-research` from topic picker (DB had stale record without matching yaml)
- Progress bar descriptions now include units:
  - `(batches)` for survey-mining, dedup
  - `(papers)` for enrich, keywords-filter, classify, taxonomy, fulltext, citation, deepdive, summary, short-titles
  - `(categories)` for category-desc

## 7. Skill Reference Template

`src/skills/skill_survey_mining_prompt.py` added generic `reference_template` with `{PLACEHOLDER}`s (topic-agnostic scaffolding validated on `llm-context-management`).

---

## Verification

```bash
# Small-scale test passed
survey_agent survey-mining --topic automated-research --phase discover --limit 100
# → 2 batches, 15s, progress bar [2/2] ✓
```

## 8. Survey-Mining Phase 3: Keyword Extraction (Implemented)

- `core.py`: `build_keyword_extraction_prompt` now reads topic-specific `keyword_system` from topic yaml
- `__init__.py`: full Phase 3 implementation
  - Extracts text from downloaded survey PDFs (max 20 pages, 30k chars)
  - Calls LLM per survey to extract keywords (up to `per_survey`)
  - Aggregates by frequency, filters by `min_frequency`
  - **Writes keywords directly back to `topics/<name>.yaml` (`keywords.survey_mined`)** — no intermediate JSON/TXT files
- Topic prompts enriched:
  - `automated-research.yaml`: detailed `keyword_system` with focus areas (deep research, SLR automation, citation analysis, etc.)
  - `llm-se-tools.yaml`: detailed `keyword_system` with SE tool focus areas
- Config: `per_survey: 30 → 50`

## 9. Proxy Replacement (Critical Infrastructure Fix)

**Old proxy**: `http://192.168.1.106:7890` — completely dead (`No route to host`)
**New proxy**: `socks5://10.20.197.128:7890` — verified working

### Root cause of 100% PDF download failure
- `_dl_one` in survey-mining used `httpx.Client()` which **reads env vars by default**
- Even with `stage_proxies.s03_survey_mining: ""`, the download requests fell back to `.env` proxy
- Dead proxy → `ConnectError` → 78/78 PDFs failed

### Verification (new proxy, SOCKS5)
| Service | Result |
|---------|--------|
| arXiv API | ✅ 200 |
| arXiv PDF download | ✅ 200 (2.2MB test) |
| ACL Anthology | ✅ 200 |
| Semantic Scholar | ⚠️ 429 (rate limit, but network OK) |
| OpenReview | ⚠️ 400 (param issue, but network OK) |

### Changes
- `.env`: `HTTP_PROXY` / `HTTPS_PROXY` → `socks5://10.20.197.128:7890`
- `config/network.yaml`: `http_proxy` → `socks5://10.20.197.128:7890`
- `pyproject.toml`: added `socksio>=0.2` dependency (httpx needs it for SOCKS5)
- Installed `socksio` in conda env

### Note for code
`httpx.Client(proxy=None)` **does not** disable env-var proxy reading in all httpx versions. To truly bypass, pass `proxy=""` or set `trust_env=False`. Current fix: all stages with `stage_proxies: ""` bypass correctly via `cfg.get_proxy()` returning `None`, and `.env` now points to a working SOCKS5 proxy.

---

## Ready for Full Run

```bash
# automated-research: discover already running (~11,264 batches, workers=100)
# After discover completes:
survey_agent survey-mining --topic automated-research --phase download
survey_agent survey-mining --topic automated-research --phase keywords

# llm-se-tools:
survey_agent survey-mining --topic llm-se-tools --phase discover
survey_agent survey-mining --topic llm-se-tools --phase download
survey_agent survey-mining --topic llm-se-tools --phase keywords
```
