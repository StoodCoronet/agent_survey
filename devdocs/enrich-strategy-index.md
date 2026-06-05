# Enrich Strategy Index

> Living doc — update as new fetchers are added or verified.

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
- **Coverage**: ICLR, some AAAI/NeurIPS workshops
- **Rate limit**: Very strict (~5 req)
- **Status**: ✅ Working but rate-limited
- **When to use**: After S2 + arXiv both fail

## 4. NDSS Venue Fetcher (`stages/s01_enrich/strategies/ndss.py`)
- **Method**: `httpx.get()` + regex on WordPress `<article>` paragraphs
- **URL pattern**: `https://www.ndss-symposium.org/ndss-paper/...`
- **Coverage**: NDSS 2023–2025
- **Status**: ✅ Verified working
- **When to use**: NDSS papers where S2 fails

## 5. USENIX Venue Fetcher (`stages/s01_enrich/strategies/usenix.py`)
- **Method**: `httpx.get()` + regex on Drupal description field
- **URL pattern**: `https://www.usenix.org/conference/.../presentation/...`
- **Coverage**: USS (USENIX Security) 2023–2025
- **Status**: ✅ Verified working
- **When to use**: USS papers where S2 fails (S2 coverage ~3-10%)

## 6. ACM DL Playwright (`stages/s01_enrich/strategies/acm.py`)
- **Method**: Playwright browser page → DOM selectors
- **URL pattern**: `https://dl.acm.org/doi/...`
- **Selectors tried**: `div.abstractInFull`, `section#abstract p`, `div.abstractSection p`
- **Status**: ⏳ Code written, not tested (Cloudflare blocks headless server)
- **When to use**: ACM venues (CCS, CHI, ICSE, ASE, etc.) where S2/arXiv fail

## 7. IEEE Xplore Playwright (`stages/s01_enrich/strategies/ieee.py`)
- **Method**: Playwright browser page → DOM selectors
- **URL pattern**: `https://ieeexplore.ieee.org/document/...`
- **Selectors tried**: `div.abstract-text`, `div.abstract div`, `section#abstract p`
- **Status**: ⏳ Code written, not tested
- **When to use**: IEEE venues (SP, TSE, etc.)

## 8. arXiv Search via Playwright (`stages/s01_enrich/web.py::_search_arxiv`)
- **Method**: Playwright browser → arxiv.org search page → scrape result
- **Coverage**: Papers with arXiv preprints not found via API
- **Status**: ✅ Working (used in `enrich-web`)
- **When to use**: `enrich-web` fallback stage

## Strategy Decision Tree

```
For each paper:
1. S2 search_by_title(title)
   └─ ✅ Found → done
   └─ ❌ Not found → 2

2. arXiv search_title(title)
   └─ ✅ Found → done
   └─ ❌ Not found → 3

3. OpenReview search_title(title)
   └─ ✅ Found → done
   └─ ❌ Not found → 4

4. Venue-specific fetcher (if venue in VENUE_FETCHERS and url exists)
   ├─ NDSS → fetch_ndss_abstract(url)
   ├─ USS → fetch_usenix_abstract(url)
   └─ ✅ Found → done
   └─ ❌ Not found → 5

5. enrich-web fallback (Playwright)
   ├─ URL contains dl.acm.org → fetch_acm_abstract(browser, url)
   ├─ URL contains ieeexplore.ieee.org → fetch_ieee_abstract(browser, url)
   └─ Default → _search_arxiv(browser, title)
```

## Known Gaps

| Venue | Year | Gap | Planned Fix |
|-------|------|-----|-------------|
| USS | 2023-2025 | S2 fails | `fetch_usenix_abstract` (ready, just needs full run) |
| NDSS | 2023 | S2 fails | `fetch_ndss_abstract` (ready, just needs full run) |
| CHI | 2023-2024 | S2 low, no arXiv | ACM DL Playwright |
| ICML | 2023 | S2 low | arXiv preprints + ACM DL Playwright |
| COLM | 2024 | S2 low | arXiv preprints |
| NeurIPS | 2023 | S2 low | arXiv preprints |
