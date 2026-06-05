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

## Ready for Full Run

```bash
survey_agent survey-mining --topic automated-research --phase discover
survey_agent survey-mining --topic llm-se-tools --phase discover
```
