# 2026-06-06 Daily Changelog

## Yesterday's Carry-over

- automated-research `survey-mining discover` — in progress (~56K papers, batch_size=5, workers=100)
- Proxy IP `10.20.197.128:7890` — confirmed blacklisted by arXiv & S2 (429 persists after 240s backoff)

---

## Today's Work

### 1. Proxy Diagnosis (Completed)

**Finding**: SOCKS5 proxy `10.20.197.128:7890` is **blacklisted**, not just rate-limited.

Evidence:
- arXiv API: 429 even after 240s backoff (4 minutes)
- S2 API: 429 after 240s backoff
- SSL EOF errors on repeated retries

**Conclusion**: The exit IP has been used by many scrapers and is on arXiv/S2 permanent/temp blacklist.

**Action**: Wait until tomorrow to test if the ban lifts. If not, need a clean IP.

---

### 2. External APIs & Keys Reference (New Doc)

Created [`external-apis.md`](external-apis.md) documenting:
- Current key inventory (DeepSeek ✅, S2 ✅)
- APIs that need keys (OpenReview, CORE)
- APIs that don't need keys but have best practices (arXiv, CrossRef, Unpaywall)
- Application links and rate limits

### 3. Agent Markdown Skills (New)

Created two agent-playbook skills under `src/skills/`:

- [`skill_core_download.md`](../src/skills/skill_core_download.md) — CORE API v3 workflow for discovering and downloading OA PDFs when arXiv/S2 fail.
- [`skill_crossref_resolve.md`](../src/skills/skill_crossref_resolve.md) — CrossRef REST API workflow for canonical DOI/metadata resolution and publisher link discovery.

Both include trigger conditions, input/output schemas, step-by-step procedures, rate-limit handling, fallback chains, and integration points.

**Tomorrow's task**: Apply for OpenReview API token + CORE API key.

---

## Immediate Next Steps (Today / Tomorrow)

| # | Task | Owner | Status |
|---|------|-------|--------|
| 1 | Test proxy IP recovery (arXiv/S2) | User | ⏳ Tomorrow |
| 2 | Apply OpenReview API token | User | ⏳ Tomorrow |
| 3 | Apply CORE API key | User | ⏳ Tomorrow |
| 4 | Continue automated-research discover | User | 🔄 In progress |
| 5 | Run download + keywords after proxy fixed | User | ⏳ Blocked |

---

## Ready Commands

```bash
# Test proxy recovery tomorrow
PYTHONUNBUFFERED=1 conda run -n survey_agent python test_api_with_backoff.py

# Continue discover (if interrupted)
survey_agent survey-mining --topic automated-research --phase discover

# After proxy fixed:
survey_agent survey-mining --topic automated-research --phase download
survey_agent survey-mining --topic automated-research --phase keywords
```
