# PDF Download Strategy

## Background

The pipeline has two stages that download PDFs:

1. **fulltext (s08)** — Downloads arXiv PDFs for papers classified as core/related/adjacent. Single-source (arxiv only), high volume (~hundreds).
2. **survey-mining download (s03)** — Downloads PDFs for survey candidates discovered by LLM scanning. Multi-source (arxiv, ACM, IEEE, author homepages, OpenReview), lower volume (~tens to hundreds).

## Current Strategies

### fulltext (s08) — Existing Implementation

```python
# core.py
def download_one(r, cfg, pdf_dir, force, db_path, topic_name):
    arxiv_id = r["arxiv_id"]
    safe = arxiv_id.replace("/", "_")
    dest = pdf_dir / f"{safe}.pdf"

    # 1. Skip if exists (>1KB) and not force
    if dest.exists() and dest.stat().st_size > 1024 and not force:
        # Update DB pdf_path if missing
        return {"status": "skipped"}

    # 2. Download via httpx stream
    http = httpx.Client(timeout=60, headers={"User-Agent": cfg.user_agent})
    if arxiv_src.download_pdf(http, arxiv_id, dest):
        db.update_paper(paper_id, {"pdf_path": str(dest)})
        return {"status": "ok"}
    else:
        return {"status": "failed"}
```

**Key design decisions:**
- Only arxiv_id-based downloads (no title search, no other sources)
- File existence check: `dest.exists() and size > 1024`
- Worker count configurable (default 1, can be increased)
- No retry logic — single attempt
- DB stores absolute path (portability issue across machines)

### survey-mining download (s03) — Current Implementation

```python
# Two-phase process:
# 1. Build manifest: look up arxiv_id/pdf_url from DB
# 2. Resolve missing: arxiv title search for papers without source
# 3. Download: concurrent download with file-system dedup
```

**Key design decisions:**
- Per-venue source lookup (DB arxiv_id / pdf_url)
- arXiv title search fallback for missing papers (3s rate limit)
- File existence check via DB `pdf_path` + filesystem check
- 5 concurrent download workers
- No retry, no source-specific rate limiting
- DB stores relative path (portable)

## Issues Discovered

### 1. Title Mismatch Between DB and arXiv

**Example:**
- DB title: `RingAttention with Blockwise Transformers for Near-Infinite Context`
- arXiv title: `Ring & Attention with Blockwise Transformers for Near-Infinite Context`

**Root cause:** arXiv search uses `ti:"exact title"` query. If the DB title differs from arXiv title (CamelCase vs space-separated, missing `&`, etc.), the search returns no results or wrong paper.

**Proposed fix:**
- Preprocess title before search: split CamelCase, normalize spaces
- Use keyword-based search (`ti:(word1 AND word2 AND word3)`) instead of exact title
- Try multiple title variants if first fails

### 2. arXiv API Rate Limit

- Official: 3 seconds between requests
- Current: configurable `delay` parameter (default 3.0)
- Violation causes `429` or SSL timeout

**Proposed fix:**
- Respect 3s minimum for search API
- PDF downloads have no official rate limit, but polite 0.5-1s interval

### 3. Mixed Sources Without Isolation

Current download pool mixes arxiv (reliable) and ACM (403-prone) URLs in the same worker pool.

**Proposed fix:**
- Separate download queues by source type
- arxiv: 5-10 workers, no delay
- ACM/IEEE: 1-2 workers, 5-10s delay, session cookies
- Author homepages: 1 worker, 3s delay

### 4. No Retry for Transient Failures

Current: one attempt, permanent failure.

**Proposed fix:**
- Retry 429/timeout with exponential backoff (max 3 attempts)
- Do not retry 404 / 403 (permanent)

## Download Priority (Decided)

### Tier 1: arXiv (Primary)
- Always try arXiv first for every paper.
- If `arxiv_id` exists in DB → direct PDF download.
- If no `arxiv_id` → `search_title` with multiple variants (CamelCase split, `&` removal, keyword fallback).
- Rate limit: 3s between API searches; 0.5s between PDF downloads.

### Tier 2: Venue-Specific Fallback

| Venue Group | Venues | Fallback Source | URL Pattern |
|-------------|--------|-----------------|-------------|
| AI / ML | ICLR, ICML, NeurIPS, COLM | **OpenReview** | `https://openreview.net/forum?id=<id>` → `https://openreview.net/pdf?id=<id>` |
| NLP | ACL, EMNLP, NAACL | **ACL Anthology** | `https://aclanthology.org/{dblp_id}.pdf` |

- After arXiv fails, route to the venue-appropriate Tier 2 source.
- No cross-venue fallback (e.g., do NOT search ACL Anthology for ICLR papers).

### Tier 3: Google Search (Global Fallback)

When arXiv API is throttled (slow/429) and OpenReview has no match, use **Google Search** as the last resort:

- **Query**: raw paper title (NO `site:` prefix — `site:arxiv.org` often misses the actual paper because the title may only appear in references).
- **Proxy**: route through user-provided HTTP proxy (from `.env`) to avoid IP throttling.
- **Extraction**: parse Google result HTML with regex:
  - arXiv: `arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})`
  - OpenReview: `openreview\.net/forum\?id=([A-Za-z0-9_-]+)`
- **Validation**: check whether the **first** search result (or first few results) contains an arXiv or OpenReview link **and** the result title loosely matches the query title (normalized comparison). If neither condition is met → mark as `missing` and stop.

**Why Google works when arXiv API fails:**
- Google indexes both the arXiv abstract page and the conference version, even if the exact wording differs slightly.
- Example: searching `"RingAttention with Blockwise Transformers for Near-Infinite Context"` on Google returns `arxiv.org/abs/2310.01889` as the #1 result and `openreview.net/forum?id=...` as #3, even though the arXiv API exact-title search fails due to the missing space.

### Tier 4: Corner Cases (Manual)
- AAAI → aaai.org/library (partial coverage) or ACM DL
- CHI / ICSE / TOSEM → ACM DL (requires cookie/institution, 403-prone)
- USS / IEEE venues → IEEE Xplore (requires institutional access)
- SE venues without open access → Author homepage (hardcoded mappings)
- Everything else → Mark as `missing`, generate manual download list

## Proposed Unified Strategy

### Source Classification

| Source | Reliability | Workers | Delay | Notes |
|--------|------------|---------|-------|-------|
| arXiv PDF | High | 5-10 | 0.5s | Direct PDF link, no auth |
| arXiv API | Medium | 1 (serial) | 3s | Search/title lookup |
| OpenReview | High | 3-5 | 1s | Forum pages, often has PDF |
| ACM DL | Low | 1 | 5-10s | Requires cookie/session |
| IEEE Xplore | Low | 1 | 5-10s | Requires institutional access |
| Author homepage | Variable | 1 | 3s | Hardcoded mappings |

### Title Search Strategy (for arXiv API)

```python
def normalize_title_for_search(title: str) -> list[str]:
    """Generate multiple search variants from a title."""
    variants = [title]
    
    # Split CamelCase: RingAttention -> Ring Attention
    camel_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', title)
    if camel_split != title:
        variants.append(camel_split)
    
    # Remove & and normalize spaces
    no_amp = title.replace('&', ' ')
    variants.append(no_amp)
    
    # Extract keywords (first 5 content words, remove stopwords)
    words = [w for w in title.split() if w.lower() not in STOPWORDS][:5]
    variants.append(' '.join(words))
    
    return variants

def search_title_robust(client, title, delay=3.0):
    for variant in normalize_title_for_search(title):
        result = _search_exact(client, variant, delay)
        if result:
            return result
    return None
```

### Title Matching Strategy (for verification)

```python
def normalize_for_compare(s: str) -> str:
    """Strip all spaces and non-alphanumeric chars for loose comparison."""
    return re.sub(r'[^a-z0-9]', '', s.lower())

def titles_match(t1: str, t2: str) -> bool:
    n1, n2 = normalize_for_compare(t1), normalize_for_compare(t2)
    return n1 == n2 or (len(n1) > 20 and len(n2) > 20 and n1[:40] == n2[:40])
```

### Retry Policy

```python
RETRY_CONFIG = {
    429: {"max_retries": 3, "backoff": [5, 10, 30]},  # rate limit
    "timeout": {"max_retries": 2, "backoff": [3, 10]},
    404: {"max_retries": 0},  # permanent
    403: {"max_retries": 1, "backoff": [5]},  # maybe cookie expired
}
```

### OpenReview as Fallback

For AI venues (ICLR, ICML, NeurIPS), OpenReview often has PDFs:
- Search: `https://api.openreview.net/notes/search?term=<title>&group=all`
- PDF: `https://openreview.net/pdf?id=<forum_id>`
- No rate limit observed, but polite 1s delay

**Implementation:** After arXiv search fails, try OpenReview search before marking as missing.

## Lessons for fulltext Migration (After survey-mining Stabilizes)

Once the survey-mining download strategy is fully validated, the following improvements should be backported to **fulltext (s08)**:

| Improvement | Current fulltext | Target (from survey-mining) |
|-------------|------------------|----------------------------|
| **Path storage** | Absolute path (`/home/.../output/pdfs/xxx.pdf`) | Relative path (`output/pdfs/xxx.pdf`) |
| **Existence check** | Filesystem only | DB `pdf_path` + filesystem |
| **Workers** | Configurable, default 1 | Source-specific pools (arxiv: 5-10) |
| **Retry** | None | 429/timeout: 3 retries with backoff |
| **Logging** | Minimal (ok/skipped/failed) | Per-item progress + summary stats |
| **Source** | arxiv only | arxiv first, then OpenReview fallback for AI venues |

**Migration trigger:** When survey-mining download runs successfully end-to-end with <5% failure rate and <10% false-positive title matching.

## Action Items

1. [x] Update `arxiv.search_title` to try multiple title variants
2. [x] Update title normalization to strip all non-alphanum chars
3. [x] Add OpenReview search fallback (`search_title_pdf`)
4. [x] Add Google Search fallback strategy (documented)
5. [ ] Implement Google Search scraping module (`services/google_search.py`)
6. [ ] Integrate Google Search into survey-mining download phase
7. [ ] Add source-specific download queues (arxiv / OpenReview / Google / ACM)
8. [ ] Add retry logic with exponential backoff
9. [ ] Survey-mining: separate arxiv-resolve phase from download phase with clear progress logging
10. [ ] Backport validated strategies to fulltext (see "Lessons for fulltext Migration")
