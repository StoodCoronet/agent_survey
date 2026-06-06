# Skill: CORE API v3 Paper Discovery & Download

## Role
Agent playbook for resolving paper titles to downloadable PDFs using the [CORE API v3](https://api.core.ac.uk/docs/v3).

## Trigger
Use this skill when:

- arXiv, Semantic Scholar, or OpenReview fail to return a PDF for a paper.
- You need to discover an open-access (OA) PDF from a title / DOI / author list.
- You are working in `s02_enrich`, `s03_survey_mining` download phase, or `s08_fulltext`.

## Goal
Find a reliable `downloadUrl` or `fullTextLink` for a given paper and download the PDF, while respecting CORE rate limits and mimicking a normal user.

## Inputs

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | str | ✅ | Full paper title (sanitize quotes) |
| `authors` | list[str] | optional | Helps disambiguate identical titles |
| `year` | int | optional | Strong filter for matching |
| `doi` | str | optional | Highest-confidence input; use `/v3/discover` |
| `venue` | str | optional | Helps sanity-check the result |

## Outputs

| Field | Type | Meaning |
|-------|------|---------|
| `core_id` | int / str | CORE internal work ID |
| `match_confidence` | float | 0.0–1.0 based on title similarity + year + authors |
| `download_url` | str \| None | Direct PDF URL from CORE |
| `full_text_link` | str \| None | Publisher OA landing page |
| `oa_status` | bool | Whether CORE marks this as open access |
| `pdf_path` | str \| None | Local path if download succeeded |
| `error` | str \| None | Human-readable failure reason |

## Authentication

- Set header: `Authorization: Bearer {CORE_API_KEY}`
- Config key: `CORE_API_KEY` in `.env`
- Free academic tier: 10k requests/month (verify current tier at https://core.ac.uk/services/api)

## Rate Limits (observed)

| Tier | Daily | Per-minute | Full-text? |
|------|-------|------------|------------|
| Unauthenticated | 100/day | — | ❌ no full-text |
| Personal | 1000/day | 25/min | ✅ |
| Academic/Institution | 5000/day | 10/min | ✅ |

**Behavior:**
- Read `X-RateLimit-Remaining` and `X-RateLimit-Limit` from every response.
- If `429` returned, sleep `60s → 120s → 240s` (exponential backoff) before retry.
- Never exceed **1 request per 6 seconds** (10/min) to stay safely inside academic tier.
- Cache successful lookups in `core_lookup_cache` (key: `title[:80].lower()`) to avoid duplicate calls.

## Procedure

### Step 1 — Prefer DOI if available
If `doi` is provided:

```
POST https://api.core.ac.uk/v3/discover
Content-Type: application/json
Authorization: Bearer {CORE_API_KEY}

Body: {"doi": "<doi>"}
```

- Response contains `works[]` with `id`, `downloadUrl`, `fullTextLink`, `title`.
- If `downloadUrl` exists → go to Step 5.
- If only `fullTextLink` → go to Step 4 (landing-page probe).
- If empty → fall back to title search (Step 2).

### Step 2 — Search works by title
If no DOI or Step 1 returned nothing:

```
GET https://api.core.ac.uk/v3/search/works?q=title:"<escaped_title>"&limit=5
```

- Quote the title with `title:"..."`.
- Escape internal `"` as `\"` and URL-encode the query string.
- Inspect `results[].work` for each candidate.

### Step 3 — Pick best candidate
For each candidate, compute:

```python
score = title_similarity(candidate.title, input.title) * 0.6 \
        + year_match(candidate.year, input.year) * 0.25 \
        + author_overlap(candidate.authors, input.authors) * 0.15
```

**Thresholds:**
- `score >= 0.90` → high-confidence match, proceed.
- `0.75 <= score < 0.90` → ambiguous; log both titles, ask caller (or pick if only one close).
- `score < 0.75` → reject; return `error = "no confident CORE match"`.

Title similarity: use rapidfuzz `fuzz.ratio` normalized to 0–1.

### Step 4 — Resolve outputs for matched work
Using the matched `work.id`:

```
GET https://api.core.ac.uk/v3/works/{id}/outputs
```

Look for:
- `downloadUrl` — direct PDF link (preferred)
- `fullTextLink` — OA landing page (fallback)
- `links[]` — any `type: download` or `format: pdf`

If no direct PDF but `fullTextLink` exists, do a **light HTTP HEAD** on the landing page and look for:
- `<meta name="citation_pdf_url" content="...">`
- `<a href="...pdf">` with text matching "Download PDF" / "PDF"
- Redirect chain ending in `.pdf`

**Do not** scrape the entire publisher site; one HEAD + one GET for the PDF is enough.

### Step 5 — Download PDF
If `downloadUrl` resolved:

```
GET {downloadUrl}
Headers:
  User-Agent: Mozilla/5.0 (compatible; survey-agent/1.0; +https://your-org.example)
  Accept: application/pdf
```

- Verify `Content-Type` starts with `application/pdf`.
- Verify file size >= 10 KB (prevent HTML error pages).
- Save to configured PDF directory.
- On `429` / `403` / `5xx`, retry with backoff (max 3 attempts).
- On success return `pdf_path`.

### Step 6 — Fallback chain
If CORE fails at any step, pass the paper to the next resolver:

1. arXiv title search
2. Semantic Scholar `paper/{id}` → `openAccessPdf`
3. Unpaywall (`https://api.unpaywall.org/v2/{doi}?email=...`)
4. Publisher landing page meta-tag probe
5. Playwright (last resort; human-like click delay 1–3s)

Record the **first successful source** in DB (`download_source = 'core'`).

## Integration Points

| Stage | File | How to use |
|-------|------|------------|
| `s02_enrich` | `src/agent_survey/stages/s01_enrich/__init__.py` | After S2/arXiv fail, call CORE to get abstract + `arxiv_id` surrogate |
| `s03_survey_mining download` | `src/agent_survey/stages/s03_survey_mining/download.py` | Try CORE before Playwright fallback |
| `s08_fulltext` | `src/agent_survey/stages/s04_fulltext.py` | For core/related papers missing local PDF |

## Decision Log

- **Why CORE first over Unpaywall?** CORE often returns a direct `downloadUrl` even when Unpaywall only has a landing page.
- **Why quote title with `title:"..."`?** CORE's search grammar supports fielded search; quoting reduces false positives.
- **Why 0.90 threshold?** CORE index contains pre-prints, duplicates, and chapters; strict matching prevents downloading the wrong paper.
- **Why cache?** Academic queries repeat across stages (enrich → fulltext); caching saves quota.

## Example Session

```
Input:
  title: "A Survey of Large Language Models for Code: Evolution, Benchmarking, and Future Trends"
  year: 2024
  doi: null

Step 2:
  GET /v3/search/works?q=title:"A%20Survey%20of%20Large%20Language%20Models%20for%20Code"&limit=5
  → 1 result: work.id = 123456789

Step 3:
  title_similarity = 0.98, year_match = 1.0 → score 0.96 ✓

Step 4:
  GET /v3/works/123456789/outputs
  → downloadUrl: https://core.ac.uk/download/pdf/123456789.pdf

Step 5:
  GET downloadUrl → 200, 1.2 MB PDF saved
  → return pdf_path = "output/automated-research/pdfs/123456789.pdf"
```

## Error Catalog

| Error | Meaning | Action |
|-------|---------|--------|
| `401 Unauthorized` | `CORE_API_KEY` missing or invalid | Alert user, halt CORE attempts |
| `429 Too Many Requests` | Quota or rate limit hit | Backoff 60→120→240s; if persists, skip to next source |
| `404 No works found` | Title not in CORE index | Fallback to Unpaywall / landing page |
| `match score < 0.75` | Candidate exists but unsure | Log for manual review; do not download |
| `downloadUrl 403` | CORE has metadata but publisher blocks PDF | Try `fullTextLink` landing page |
| `Content-Type text/html` | Received an error page instead of PDF | Retry once; then fallback |
