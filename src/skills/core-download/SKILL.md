---
name: core-download
description: Discover and download open-access PDFs using the CORE API v3. Use this skill whenever arXiv, Semantic Scholar, or OpenReview fail to return a PDF, when you need to resolve a paper title to a downloadable OA PDF, or when working in the enrich, survey-mining download, or fulltext stages and the primary sources are exhausted.
---

# CORE API v3 Paper Discovery & Download

Resolve paper titles (and optionally DOIs) to downloadable open-access PDFs using [CORE API v3](https://api.core.ac.uk/docs/v3).

## When to use

- arXiv / Semantic Scholar / OpenReview returned no PDF.
- You have a title (and maybe authors + year) and need an OA PDF.
- You are in `s02_enrich`, `s03_survey_mining download`, or `s08_fulltext` and the primary source chain failed.

## Inputs

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | str | yes | Full paper title; escape internal quotes |
| `authors` | list[str] | no | Helps disambiguate duplicate titles |
| `year` | int | no | Strong filter for matching |
| `doi` | str | no | Highest-confidence input |
| `venue` | str | no | Sanity-check only |

## Outputs

| Field | Type | Meaning |
|-------|------|---------|
| `core_id` | int/str | CORE work ID |
| `match_confidence` | float | 0.0–1.0 composite score |
| `download_url` | str/None | Direct PDF URL from CORE |
| `full_text_link` | str/None | OA landing page |
| `oa_status` | bool | CORE open-access flag |
| `pdf_path` | str/None | Local path after successful download |
| `error` | str/None | Human-readable failure reason |

## Auth & rate limits

Set header `Authorization: Bearer {CORE_API_KEY}`. Store `CORE_API_KEY` in `.env`.

Observed limits:

| Tier | Daily | Per-minute | Full-text? |
|------|-------|------------|------------|
| Unauthenticated | 100/day | — | no |
| Personal | 1000/day | 25/min | yes |
| Academic | 5000/day | 10/min | yes |

Behavior:
- Read `X-RateLimit-Remaining` and `X-RateLimit-Limit` on every response.
- On `429`, back off 60s → 120s → 240s before retry.
- Stay under **1 request per 6 seconds** to safely fit academic tier.
- Cache successful lookups by `title[:80].lower()` to avoid duplicate calls.

## Procedure

### 1. Prefer DOI when available

```
POST https://api.core.ac.uk/v3/discover
Content-Type: application/json
Authorization: Bearer {CORE_API_KEY}

{"doi": "<doi>"}
```

- If `downloadUrl` exists → go to step 5.
- If only `fullTextLink` → go to step 4 (landing-page probe).
- If empty → fall back to title search (step 2).

### 2. Search works by title

```
GET https://api.core.ac.uk/v3/search/works?q=title:"<escaped_title>"&limit=5
```

- Wrap title in `title:"..."`.
- Escape `"` as `\"` and URL-encode the full query.

### 3. Pick the best candidate

Compute a composite score for each candidate:

```python
score = title_similarity(candidate.title, input.title) * 0.60 \
        + year_match(candidate.year, input.year) * 0.25 \
        + author_overlap(candidate.authors, input.authors) * 0.15
```

Use rapidfuzz `fuzz.ratio` for title similarity, normalized to 0–1.

Thresholds:
- `score >= 0.90` → high-confidence match, proceed.
- `0.75 <= score < 0.90` → ambiguous; log both titles and ask the caller (or pick if only one close).
- `score < 0.75` → reject with `error = "no confident CORE match"`.

### 4. Resolve outputs for the matched work

```
GET https://api.core.ac.uk/v3/works/{id}/outputs
```

Priority:
1. `downloadUrl` — direct PDF (best)
2. `links[]` with `type: download` or `format: pdf`
3. `fullTextLink` — OA landing page

If only a landing page is available, do a light HTTP HEAD/GET and look for:
- `<meta name="citation_pdf_url" content="...">`
- `<a href="...pdf">` with text matching "Download PDF" / "PDF"
- Redirect chain ending in `.pdf`

Stop after locating the PDF link. Do not spider the publisher site.

### 5. Download the PDF

```
GET {download_url}
User-Agent: Mozilla/5.0 (compatible; survey-agent/1.0)
Accept: application/pdf
```

Validate:
- `Content-Type` starts with `application/pdf`.
- File size >= 10 KB.

Retry logic:
- On `429`, `403`, or `5xx`, retry up to 3 times with exponential backoff.
- On success, save to the configured PDF directory and return `pdf_path`.

## Fallback chain

If CORE fails, try in order:

1. arXiv title search
2. Semantic Scholar `paper/{id}` → `openAccessPdf`
3. Unpaywall: `https://api.unpaywall.org/v2/{doi}?email=...`
4. Publisher landing page meta-tag probe
5. Playwright (last resort; human-like click delay 1–3s)

Record the first successful source in the DB (`download_source = 'core'`).

## Integration points

| Stage | File | Usage |
|-------|------|-------|
| `s02_enrich` | `src/agent_survey/stages/s01_enrich/__init__.py` | Fallback for abstract + arxiv_id surrogate |
| `s03_survey_mining download` | `src/agent_survey/stages/s03_survey_mining/download.py` | Try before Playwright fallback |
| `s08_fulltext` | `src/agent_survey/stages/s04_fulltext.py` | Download PDFs for core/related papers |

## Why these choices

- **CORE over Unpaywall first**: CORE often exposes a direct `downloadUrl` when Unpaywall only has a landing page.
- **Quoted title search**: Fielded `title:"..."` queries reduce false positives in a 200M+ index.
- **Strict 0.90 threshold**: The index contains duplicates, preprints, and book chapters; strict matching prevents wrong-paper downloads.
- **Title cache**: The same paper is often queried across enrich → fulltext; caching preserves quota.

## Example

Input:

```json
{
  "title": "A Survey of Large Language Models for Code: Evolution, Benchmarking, and Future Trends",
  "year": 2024,
  "doi": null
}
```

Flow:

1. Search: `GET /v3/search/works?q=title:"A%20Survey%20of%20Large%20Language%20Models%20for%20Code"&limit=5`
2. Match: `work.id = 123456789`, title similarity 0.98, year match 1.0 → score 0.96.
3. Outputs: `GET /v3/works/123456789/outputs` → `downloadUrl` found.
4. Download PDF → save to `output/automated-research/pdfs/123456789.pdf`.

## Error catalog

| Error | Meaning | Action |
|-------|---------|--------|
| `401 Unauthorized` | `CORE_API_KEY` missing or invalid | Alert user; halt CORE attempts |
| `429 Too Many Requests` | Rate/quota limit | Backoff 60→120→240s; fallback if persistent |
| `404 No works found` | Title not in CORE index | Fallback to Unpaywall / landing page |
| `match score < 0.75` | Candidate exists but unsure | Log for manual review; do not download |
| `downloadUrl 403` | Publisher blocks direct PDF | Try `fullTextLink` landing page |
| `Content-Type text/html` | Error page instead of PDF | Retry once; then fallback |
