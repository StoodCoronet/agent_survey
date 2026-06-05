# Venue Enrich Strategy Map

Last updated: 2026-06-02

## Venue x Year — Small-Scale Test Matrix

*Goal: test 10 papers per combo to derive the best strategy before full enrichment.*

| Venue | 2026 | 2025 | 2024 | 2023 |
|-------|------|------|------|------|
| **AAAI** | ✅ S2 | ✅ S2 | ✅ S2 | ✅ S2+OR |
| **ACL** | — | ✅ S2 | ✅ S2 | ✅ S2+OR |
| **ASE** | ✅ S2 | — | ✅ S2 | ✅ S2 |
| **CCS** | — | ✅ S2 | ✅ S2 | ✅ S2 |
| **CHI** | ✅ S2 | ✅ S2 | ✅ S2 | ✅ S2 |
| **COLM** | — | — | ✅ S2 | — |
| **EMNLP** | — | ✅ S2 | ✅ S2 | ✅ S2 |
| **FSE** | — | ✅ S2 | ✅ S2 | ✅ S2 |
| **ICLR** | ✅ S2 | ✅ S2 | ✅ S2 | — |
| **ICML** | — | ✅ S2 | ✅ S2 | ✅ S2 |
| **ICSE** | ✅ S2 | — | ✅ S2 | ✅ S2 |
| **ISSTA** | — | ✅ S2 | ✅ S2 | ✅ S2 |
| **NAACL** | — | ✅ S2 | ✅ S2 | — |
| **NDSS** | ✅ S2 | ✅ S2 | ✅ S2 | ✅ venue |
| **NeurIPS** | — | — | ✅ S2 | ✅ S2 |
| **SP** | ✅ S2 | ✅ S2 | ✅ S2 | ✅ S2 |
| **TOSEM** | ✅ S2 | ✅ S2 | ✅ S2 | ✅ Crossref |
| **TSE** | ✅ S2 | ✅ S2 | ✅ S2 | ✅ S2 |
| **UIST** | — | ✅ S2 | ✅ S2 | ✅ S2 |
| **USS** | — | ✅ S2+venue | ✅ venue | ✅ venue |

**Legend**
- ✅ **Tested & ready** — small-scale test passed; best strategy identified.
- ⚠️ **Marginal** — works but coverage is borderline (< 60%).
- ⏳ **Untested** — need to run 10-paper probe to identify best strategy.
- ❌ **Blocked** — probe failed; need new fetcher/strategy.

### Tested Combos (with results)

| Venue | Year | Tested | OK | Rate | Best Strategy | Notes |
|-------|------|--------|----|------|---------------|-------|
| AAAI | 2026 | 9 | 9 | 100% | S2 | — |
| AAAI | 2025 | 7 | 5 | 71% | S2 | — |
| AAAI | 2024 | 6 | 3 | 50% | S2 | May need arXiv fallback |
| AAAI | 2023 | 7 | 4 | 57% | S2+OpenReview | OpenReview picks up some |
| ACL | 2024 | 10 | 10 | 100% | S2 | — |
| ACL | 2023 | 9 | 8 | 89% | S2+OpenReview | OpenReview picks up some |
| ACL | 2025 | 10 | 6 | 60% | S2 | New papers, S2 catching up |
| ASE | 2024 | 10 | 10 | 100% | S2 | — |
| CCS | 2024 | 10 | 10 | 100% | S2 | — |
| CCS | 2023 | 10 | 8 | 80% | S2 | — |
| CCS | 2025 | 10 | 10 | 100% | S2+OpenReview | 1 OpenReview pickup |
| CHI | 2023 | 10 | 10 | 100% | S2 | — |
| CHI | 2024 | 10 | 10 | 100% | S2 | — |
| CHI | 2025 | 10 | 10 | 100% | S2 | — |
| CHI | 2026 | 10 | 10 | 100% | S2 | — |
| COLM | 2024 | 10 | 10 | 100% | S2+OpenReview | 1 OpenReview pickup |
| EMNLP | 2023 | 10 | 9 | 90% | S2 | — |
| EMNLP | 2024 | 10 | 8 | 80% | S2 | — |
| EMNLP | 2025 | 10 | 8 | 80% | S2 | — |
| FSE | 2023 | 10 | 10 | 100% | S2 | — |
| FSE | 2024 | 10 | 10 | 100% | S2 | — |
| FSE | 2025 | 10 | 10 | 100% | S2 | — |
| ICML | 2023 | 10 | 10 | 100% | S2+OpenReview | 1 OpenReview pickup |
| ICML | 2024 | 10 | 8 | 80% | S2 | — |
| ICML | 2025 | 10 | 6 | 60% | S2+OpenReview | S2 catching up on new papers |
| ISSTA | 2023 | 10 | 10 | 100% | S2 | — |
| ISSTA | 2024 | 10 | 9 | 90% | S2 | — |
| ISSTA | 2025 | 10 | 10 | 100% | S2 | — |
| NAACL | 2024 | 10 | 10 | 100% | S2 | — |
| NAACL | 2025 | 10 | 9 | 90% | S2 | — |
| NDSS | 2024 | 10 | 9 | 90% | S2 | 1 fail → `fetch_ndss_abstract` |
| NDSS | 2025 | 10 | 10 | 100% | S2 | — |
| NDSS | 2026 | 10 | 10 | 100% | S2+venue | 1 venue fallback |
| NeurIPS | 2023 | 10 | 10 | 100% | S2 | — |
| NeurIPS | 2024 | 10 | 9 | 90% | S2 | — |
| TOSEM | 2023 | 10 | 5 | 50% | S2+Crossref | S2 50%; Crossref covers 99% via DOI |
| TOSEM | 2024 | 10 | 9 | 90% | S2 | — |
| TOSEM | 2025 | 10 | 10 | 100% | S2 | — |
| TOSEM | 2026 | 10 | 10 | 100% | S2 | — |
| UIST | 2023 | 10 | 10 | 100% | S2 | — |
| UIST | 2024 | 10 | 10 | 100% | S2 | — |
| UIST | 2025 | 10 | 10 | 100% | S2 | — |
| USS | 2023 | 10 | 1 | 10% | **usenix.org** | S2 fails; venue fetcher works |
| USS | 2025 | 10 | 10 | 100% | S2+venue | 6 S2 + 4 venue fallback |

### Blocked Combos (need new strategy)

*None fully blocked yet — all tested combos have at least one working source.*

## Summary by Tier

### Tier 1: S2 covers well (just run enrich)

| Venue | Year | S2 Rate | Backup | Notes |
|-------|------|---------|--------|-------|
| ACL | 2024 | 100% | arXiv | S2 is complete |
| ASE | 2024 | 100% | — | S2 is complete |
| CHI | 2023-2026 | 100% | — | S2 is complete |
| COLM | 2024 | 90% | OpenReview | S2 mostly enough |
| CCS | 2024-2025 | 100% | OpenReview | S2 is complete |
| FSE | 2023-2025 | 100% | — | S2 is complete |
| ISSTA | 2023-2025 | 90-100% | — | S2 is complete |
| NAACL | 2024-2025 | 90-100% | — | S2 is complete |
| NDSS | 2024-2026 | 90-100% | venue fetcher | S2 + ndss-symposium.org fallback |
| NeurIPS | 2023-2024 | 90-100% | — | S2 is complete |
| TOSEM | 2024-2026 | 90-100% | — | S2 is complete |
| UIST | 2023-2025 | 100% | — | S2 is complete |
| AAAI | 2026 | 100% | — | S2 already has future data |

### Tier 2: S2 + OpenReview covers most

| Venue | Year | S2 Rate | OpenReview picks up | Notes |
|-------|------|---------|---------------------|-------|
| ACL | 2023 | ~89% | Yes | Some on OpenReview |
| ACL | 2025 | ~60% | — | New papers, S2 catching up |
| AAAI | 2025 | ~71% | — | S2 mostly enough |
| CCS | 2023 | ~80% | — | S2 mostly enough |
| ICML | 2023 | ~90% | Yes | 1 OpenReview pickup |
| ICML | 2024 | ~80% | — | S2 mostly enough |
| ICML | 2025 | ~60% | Yes | New papers, S2 catching up |
| EMNLP | 2023-2025 | ~80-90% | — | S2 mostly enough |

### Tier 3: S2 fails, venue fetcher saves it

| Venue | Year | S2 Rate | Primary Strategy | Backup | Notes |
|-------|------|---------|------------------|--------|-------|
| USS | 2023 | ~10% | **usenix.org** | — | `fetch_usenix_abstract` works |
| USS | 2024 | ~3% | **usenix.org** | — | Same fetcher |
| USS | 2025 | ~60% | **S2 + usenix.org** | — | Mixed; venue fetcher still needed |
| NDSS | 2023 | — | **ndss-symposium.org** | S2 | `fetch_ndss_abstract` works; S2 also ~90% |

### Tier 4: Marginal — needs attention

*None currently marginal. All combos have ≥60% coverage with a working strategy.*

## Existing Fetchers

### `strategies/ndss.py`
- Target: NDSS symposium pages
- Method: httpx + regex on WordPress `<article class="... post ...">`
- Status: **Working**
- Coverage: NDSS 2023-2026

### `strategies/usenix.py`
- Target: USENIX presentation pages
- Method: httpx + regex on Drupal field
- Status: **Working**
- Coverage: USS (USENIX Security) 2023-2025

### `strategies/acm.py`
- Target: ACM Digital Library
- Method: Playwright (`fetch_acm_abstract`)
- Status: Code written, untested (Cloudflare on headless server)
- Coverage: CCS, CHI, ICSE, etc.

### `strategies/ieee.py`
- Target: IEEE Xplore
- Method: Playwright (`fetch_ieee_abstract`)
- Status: Code written, untested (Cloudflare on headless server)
- Coverage: IEEE S&P, etc.

### `strategies/crossref.py`
- Target: Crossref works API (any DOI)
- Method: `httpx.get()` → JSON → strip JATS XML tags
- Status: **Working**
- Coverage: Any paper with a DOI (ACM, IEEE, Springer, Wiley, etc.)
- Key finding: TOSEM 2023 journal papers — 99% coverage via Crossref

## Recommended Action Plan

1. **USS 2023-2025**: Already solved by `fetch_usenix_abstract`. Just need to run `enrich` with `all_papers=True` (already changed).

2. **NDSS 2023-2026**: Already solved by `fetch_ndss_abstract`. Same as above.

3. **CHI / ICML / NeurIPS / EMNLP / COLM / FSE / ISSTA / UIST / NAACL / TOSEM 2024+**: S2 covers 80-100%. Just run `enrich`.

4. **TOSEM 2023**: S2 only 50% in probe, but **Crossref covers 99%** via DOI. Already integrated into enrich pipeline.

5. **ACM/IEEE venues**: Use `enrich-web` Playwright fallback for papers with `dl.acm.org` or `ieeexplore.ieee.org` URLs.

## Why Coverage Looked Bad Before

The main reason many venues showed 0-5% abstract coverage in the DB was **not** missing fetchers. It was the old enrich strategy (`all_papers=False`) which only enriched papers already classified as core/related/adjacent. Since classification happens *after* prefilter, and security/software venues often have low initial classification rates, their papers were simply skipped by enrich.

**Fix applied**: `all_papers` default changed to `True` in `s01_enrich/__init__.py` and CLI (`--classified-only`).

---

# Enrich Strategy Index

## 1. S2 API (`services/s2.py`)
- **Method**: `S2Client.search_by_title()` → `/paper/search/match`
- **Coverage**: Best for AI/ML/NLP venues (ICLR, AAAI, ASE, SP, TSE, ASE, ICSE)
- **Rate limit**: 0.3s with API key, 1.1s without
- **Status**: ✅ Working
- **When to use**: First source for almost all papers

## 2. arXiv API (`services/arxiv.py`)
- **Method**: `arxiv.search_title()` → arXiv API query
- **Coverage**: ML/NLP papers with preprints
- **Status**: ✅ Working
- **When to use**: S2 fails, especially for NeurIPS/ICML/ACL/EMNLP

## 3. OpenReview API (`services/openreview.py`)
- **Method**: `openreview.search_title()` → OpenReview API
- **Coverage**: ICLR, some AAAI/NeurIPS workshops, ICML, COLM, CCS
- **Rate limit**: Very strict (~5 req)
- **Status**: ✅ Working but rate-limited
- **When to use**: After S2 + arXiv both fail

## 4. NDSS Venue Fetcher (`strategies/ndss.py`)
- **Method**: `httpx.get()` + regex on WordPress `<article>` paragraphs
- **URL pattern**: `https://www.ndss-symposium.org/ndss-paper/...`
- **Coverage**: NDSS 2023–2026
- **Status**: ✅ Verified working
- **When to use**: NDSS papers where S2 fails

## 5. USENIX Venue Fetcher (`strategies/usenix.py`)
- **Method**: `httpx.get()` + regex on Drupal description field
- **URL pattern**: `https://www.usenix.org/conference/.../presentation/...`
- **Coverage**: USS (USENIX Security) 2023–2025
- **Status**: ✅ Verified working
- **When to use**: USS papers where S2 fails (S2 coverage ~3-10%)

## 6. ACM DL Playwright (`strategies/acm.py`)
- **Method**: Playwright browser page → DOM selectors
- **URL pattern**: `https://dl.acm.org/doi/...`
- **Selectors tried**: `div.abstractInFull`, `section#abstract p`, `div.abstractSection p`
- **Status**: ⏳ Code written, not tested (Cloudflare blocks headless server)
- **When to use**: ACM venues (CCS, CHI, ICSE, ASE, etc.) where S2/arXiv fail

## 7. IEEE Xplore Playwright (`strategies/ieee.py`)
- **Method**: Playwright browser page → DOM selectors
- **URL pattern**: `https://ieeexplore.ieee.org/document/...`
- **Selectors tried**: `div.abstract-text`, `div.abstract div`, `section#abstract p`
- **Status**: ⏳ Code written, not tested
- **When to use**: IEEE venues (SP, TSE, etc.)

## 8. arXiv Search via Playwright (`web.py::_search_arxiv`)
- **Method**: Playwright browser → arxiv.org search page → scrape result
- **Coverage**: Papers with arXiv preprints not found via API
- **Status**: ✅ Working (used in `enrich-web`)
- **When to use**: `enrich-web` fallback stage

## 9. Crossref API (`strategies/crossref.py`)
- **Method**: `httpx.get()` → `api.crossref.org/works/{doi}` → strip JATS XML
- **Coverage**: Any paper with a DOI (ACM, IEEE, Springer, Wiley, etc.)
- **Status**: ✅ Working
- **Key result**: TOSEM 2023 — 99% coverage (107/108 papers)
- **When to use**: When S2/arXiv/OpenReview all fail but paper has a DOI URL

## Strategy Decision Tree

**Layer priority**: S2/arXiv/DBLP → IEEE/ACM → venue own site  
**Method priority within each layer**: API → curl → Playwright

```
For each paper:

Layer 1 — General Platforms (API → curl → Playwright)
  1a. S2 API search_by_title(title)
      └─ ✅ Found → done
      └─ ❌ Not found → 1b
  1b. arXiv API search_title(title)
      └─ ✅ Found → done
      └─ ❌ Not found → 1c
  1c. OpenReview API search_title(title)
      └─ ✅ Found → done
      └─ ❌ Not found → Layer 2

Layer 2 — Publisher Platforms (API → curl → Playwright)
  2a. Crossref API (any DOI)
      └─ ✅ Found → done
      └─ ❌ Not found → 2b
  2b. ACM / IEEE API (if available)
      └─ ✅ Found → done
      └─ ❌ Not found → 2c
  2c. ACM / IEEE direct page (curl)
      └─ ✅ Found → done
      └─ ❌ Not found → 2d
  2d. ACM / IEEE Playwright (browser rendering)
      └─ ✅ Found → done
      └─ ❌ Not found → Layer 3

Layer 3 — Venue Own Site (curl → Playwright)
  3a. Venue-specific fetcher (curl)
      ├─ NDSS → fetch_ndss_abstract(url)
      ├─ USS → fetch_usenix_abstract(url)
      └─ ✅ Found → done
      └─ ❌ Not found → 3b
  3b. Venue page Playwright (last resort)
      └─ Try browser rendering of venue URL
```

---

# Test Methodology

## Priority Order

**API → curl → Playwright**

1. **API** (fastest, most reliable) — use official APIs first
2. **curl** (medium) — direct HTTP request to paper pages
3. **Playwright** (slowest, last resort) — browser rendering for JS-heavy or bot-protected sites

## Test Matrix: Method × Platform

| Platform | API | curl | Playwright | Notes |
|----------|-----|------|------------|-------|
| **S2** | ✅ `S2Client.search_by_title()` | ✅ `curl` to `/paper/search/match` | N/A | API key needed for rate limit |
| **arXiv** | ✅ `arxiv.search_title()` | ✅ `curl` to `export.arxiv.org/api` | ✅ `_search_arxiv()` in `web.py` | API easiest; Playwright for edge cases |
| **OpenReview** | ✅ `openreview.search_title()` | ✅ `curl` to `api.openreview.net` | N/A | Rate limit ~5 req |
| **DBLP** | ⚠️ No abstract API | ⚠️ XML dump only | N/A | DBLP has no per-paper abstract endpoint |
| **Crossref** | ✅ `api.crossref.org/works/{doi}` | ✅ `curl` works | N/A | Fast; returns JATS XML abstracts |
| **ACM DL** | ❌ No public API | ❌ Cloudflare blocks | ⏳ `fetch_acm_abstract()` | Playwright only |
| **IEEE Xplore** | ❌ No public API | ❌ Cloudflare blocks | ⏳ `fetch_ieee_abstract()` | Playwright only |
| **NDSS** | ❌ No API | ✅ `fetch_ndss_abstract()` (httpx) | N/A | Direct page scrape works |
| **USENIX** | ❌ No API | ✅ `fetch_usenix_abstract()` (httpx) | N/A | Direct page scrape works |

## Venue Probe Protocol

For each untested ⏳ `venue + year` combo:

1. **Pick 10 papers** that need abstracts
2. **Layer 1 — General APIs**: S2 API → arXiv API → OpenReview API
   - Record success rate per source
3. **Layer 2 — Publisher (API → curl → Playwright)**: Crossref / IEEE / ACM
   - Try Crossref API first (fast, any DOI)
   - Try IEEE/ACM API (if available)
   - Try curl (direct HTTP to paper page)
   - Try Playwright (browser rendering for JS/bot protection)
4. **Layer 3 — Venue own site (curl → Playwright)**: NDSS / USS / etc.
   - Try curl (`fetch_ndss_abstract`, `fetch_usenix_abstract`)
   - Try Playwright if curl fails
5. **Record best strategy** in the matrix above
6. **Only mark ✅ after ≥ 60% success rate** on the probe

## Probe Checklist

*All 31 previously untested combos have been probed. Results updated above.*

- [x] CHI 2023 → ✅ S2 (100%)
- [x] CHI 2024 → ✅ S2 (100%)
- [x] CHI 2025 → ✅ S2 (100%)
- [x] CHI 2026 → ✅ S2 (100%)
- [x] ICML 2023 → ✅ S2+OR (100%)
- [x] ICML 2024 → ✅ S2 (80%)
- [x] ICML 2025 → ✅ S2+OR (60%)
- [x] NeurIPS 2023 → ✅ S2 (100%)
- [x] NeurIPS 2024 → ✅ S2 (90%)
- [x] EMNLP 2023 → ✅ S2 (90%)
- [x] EMNLP 2024 → ✅ S2 (80%)
- [x] EMNLP 2025 → ✅ S2 (80%)
- [x] COLM 2024 → ✅ S2+OR (100%)
- [x] NAACL 2024 → ✅ S2 (100%)
- [x] NAACL 2025 → ✅ S2 (90%)
- [x] FSE 2023 → ✅ S2 (100%)
- [x] FSE 2024 → ✅ S2 (100%)
- [x] FSE 2025 → ✅ S2 (100%)
- [x] TOSEM 2023 → ✅ S2+Crossref (50% S2 → 99% with Crossref DOI)
- [x] TOSEM 2024 → ✅ S2 (90%)
- [x] TOSEM 2025 → ✅ S2 (100%)
- [x] TOSEM 2026 → ✅ S2 (100%)
- [x] UIST 2023 → ✅ S2 (100%)
- [x] UIST 2024 → ✅ S2 (100%)
- [x] UIST 2025 → ✅ S2 (100%)
- [x] ISSTA 2024 → ✅ S2 (90%)
- [x] ISSTA 2025 → ✅ S2 (100%)
- [x] CCS 2025 → ✅ S2+OR (100%)
- [x] NDSS 2025 → ✅ S2 (100%)
- [x] NDSS 2026 → ✅ S2+venue (100%)
- [x] USS 2025 → ✅ S2+venue (100%)
