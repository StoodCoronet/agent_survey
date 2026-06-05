# Overall Plan — Multi-Topic Survey Agent

**Last updated**: 2026-06-05

## Topic Status Overview

| Topic | Harvest | Enrich | Survey-Mining | Keywords-Filter | Classify | Taxonomy | Dedup | Fulltext | Citation | Deepdive | Short-Titles | Summary | Category-Desc | Report |
|-------|---------|--------|---------------|-----------------|----------|----------|-------|----------|----------|----------|--------------|---------|---------------|--------|
| llm-context-management | ✅ | ✅ | ✅ | ✅ | ✅ | 🔄 | · | · | · | · | · | · | · | · |
| automated-research | ✅ | ✅ | · | · | · | · | · | · | · | · | · | · | · | · |
| llm-se-tools | ✅ | ✅ | · | · | · | · | · | · | · | · | · | · | · | · |
| llm-agent | ✅ | ✅ | · | · | · | · | · | · | · | · | · | · | · | · |

Legend: ✅ done · not started 🔄 in progress

---

## Architecture Milestones (Completed)

1. ✅ **Multi-topic DB schema** — `papers` shared, `paper_topics` per-topic, `topic_deepdive` per-topic
2. ✅ **Config split** — `config/` directory with `base.yaml`, `venues.yaml`, `network.yaml`, `llm.yaml`, `stages/*.yaml`
3. ✅ **Stage config ordering** — `s02_enrich.yaml`, `s03_survey_mining.yaml`, etc. (filesystem order = pipeline order)
4. ✅ **Per-stage proxy** — `network.stage_proxies` with `sNN_` prefix support; `.env` proxy properly overridden
5. ✅ **Worker-only + batch DB write** — classify, taxonomy, deepdive, summary, category-desc all use main-thread batch flush
6. ✅ **Bounded writer queue** — classify writer queue `maxsize=500` with backpressure
7. ✅ **Writer crash detection** — shared `writer_error` list + `queue.Full` timeout handling
8. ✅ **LLM caching** — `llm_calls` table keyed by input hash
9. ✅ **Prefilter cleanup** — removed standalone prefilter stage; keywords-filter is the single filter stage
10. ✅ **TUI topic management** — switch/create topics, pipeline status dashboard

---

## Immediate Next Steps (This Week)

### Topic: automated-research
1. ⏳ **survey-mining discover** — full run (56K papers, batch_size=50, workers=10)
2. ⏳ **keywords-filter** — keyword regex prefilter
3. ⏳ **classify** — DeepSeek-Flash batch classification
4. ⏳ **taxonomy** — multi-dimensional tree classification

### Topic: llm-se-tools
1. ⏳ **survey-mining discover** — full run
2. ⏳ **keywords-filter**
3. ⏳ **classify**
4. ⏳ **taxonomy**

### Topic: llm-context-management
1. ⏳ **taxonomy** — finish in-progress run
2. ⏳ **dedup** — sub-topic deduplication
3. ⏳ **fulltext** — PDF download for core/related papers
4. ⏳ **deepdive** — DeepSeek-Pro structured extraction
5. ⏳ **short-titles** — abbreviated title generation
6. ⏳ **summary** — bilingual 3-4 sentence summaries
7. ⏳ **category-desc** — bilingual taxonomy descriptions
8. ⏳ **report** — Obsidian vault + JSON + Markdown + static docs

---

## Medium-Term (Next 2 Weeks)

1. **llm-agent topic** — full pipeline run from harvest to report
2. **Cross-topic dedup** — papers may appear in multiple topics; ensure dedup doesn't conflict
3. **Docs site per-topic** — `generate-docs` currently overwrites; need `docs/<topic>/` isolation
4. **Citation graph** — extract citations from PDFs, build D3 graph (s09)
5. **Obsidian vault polish** — link graph, backlinks, MOC (Map of Content)

---

## Known Issues / Tech Debt

| Issue | Priority | Note |
|-------|----------|------|
| DB field `prefilter_hit` name | Low | Still called `prefilter_hit` in DB; renaming requires migration |
| `mark_stage("prefilter")` legacy key | Low | `s04_keywords_filter` writes `"prefilter"` stage key for backward compat |
| `docs/` generated files untracked | Low | Should `.gitignore` `docs/*/` or commit per-topic generated sites |
| `.claude/settings.local.json` changes | Low | IDE settings leaking into git diff |
| `test-topic` in DB | Low | Empty test topic; harmless |

---

## Design Decisions Log

1. **Batch write pattern**: Worker threads do LLM calls only; all DB writes happen in main thread via queue/pending list + periodic flush. Prevents SQLite write-lock contention.
2. **Config over env**: All stage configs live in `config/stages/*.yaml`. `.env` is fallback for secrets only. Proxy must be explicitly set per-stage in YAML.
3. **Topic yaml as SSOT**: Topic-specific prompts, keywords, taxonomy trees live in `topics/<name>.yaml`. Pipeline code is topic-agnostic.
4. **Survey mining scope**: Scans ALL papers (not prefiltered) to find cross-topic surveys. Cost is low (~$0.1-0.5 per 56K papers with batch_size=50).
