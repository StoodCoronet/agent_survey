---
name: crossref-resolve
description: Resolve paper titles or DOIs to authoritative metadata and optional open-access links using the CrossRef REST API. Use this skill when you need a canonical DOI from a free-form title, when arXiv/S2/CORE metadata disagree and you want an authoritative reference, when harvesting non-CS venues that are better indexed by CrossRef, or when you need publisher info, ISSN, page numbers, or a publisher landing-page link.
---

# CrossRef Metadata Resolution

Resolve titles and DOIs to canonical metadata using the [CrossRef REST API](https://api.crossref.org).

## When to use

- You need a canonical DOI from a free-form title.
- arXiv / S2 / CORE return inconsistent metadata and you want an authoritative record.
- You need publisher, ISSN, page numbers, or URL for a harvested paper.
- You are enriching papers from non-CS venues (HCI, IS, SE journals) better covered by CrossRef.

## Inputs

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | str | yes unless DOI given | Complete titles work best |
| `authors` | list[str] | no | Family names are enough |
| `year` | int | no | Use `filter=from-pub-date:<year>,until-pub-date:<year>` |
| `doi` | str | no | Skip search and call `/works/{doi}` directly |
| `venue_hint` | str | no | Sanity-check only |

## Outputs

| Field | Type | Meaning |
|-------|------|---------|
| `doi` | str/None | Canonical DOI |
| `title` | str/None | CrossRef-normalized title |
| `authors` | list[dict]/None | `[{family, given, affiliation, ORCID}]` |
| `year` | int/None | Published-print or published-online year |
| `venue` | str/None | `container-title` or `publisher` |
| `publisher` | str/None | Publisher name |
| `page` | str/None | Page range |
| `volume` / `issue` | str/None | Journal volume/issue |
| `issn` | list[str]/None | ISSNs |
| `url` | str/None | Landing page (usually `https://doi.org/{doi}`) |
| `pdf_url` | str/None | Direct OA PDF if linked |
| `oa_status` | bool | Whether CrossRef exposes an OA PDF link |
| `score` | float | CrossRef score or computed fallback |

## Auth & rate limits

CrossRef does not require a key, but strongly prefers a registered `mailto` for the "polite" pool.

- Register at https://www.crossref.org/services/metadata-delivery/
- Append `?mailto=YOUR_EMAIL` to every request.
- Set a descriptive `User-Agent`:
  ```
  User-Agent: survey-agent/1.0 (mailto:YOUR_EMAIL)
  ```

Limits:
- CrossRef asks for no more than 50 req/s with `mailto`.
- Stay under 5 req/s to be safe.
- On `503 Slow Down` or `429`, throttle to 1 req/s for 60s.

## Procedure

### 1. Direct DOI lookup

```
GET https://api.crossref.org/works/{doi}?mailto={EMAIL}
```

- Extract metadata from `message`.
- Check `message.link[]` for `content-type: application/pdf` or `intended-application: text-mining`.
- Return immediately.

### 2. Title search

```
GET https://api.crossref.org/works?query.title={escaped_title}&rows=5&mailto={EMAIL}
```

Best practices:
- URL-encode the title.
- Do not add extra quotes; `query.title` already boosts title fields.
- If year is known, add `&filter=from-pub-date:{year},until-pub-date:{year}`.
- If an author is known, add `&query.author={family_name}`.

### 3. Pick the best candidate

CrossRef returns `message.items[]` with a `score`. Evaluate:

1. Highest CrossRef `score`.
2. Title similarity >= 0.85 via rapidfuzz `fuzz.ratio`.
3. Year match (if provided).
4. Author overlap (if provided).

Decision:
- `crossref_score >= 80` and title similarity >= 0.90 → accept.
- `crossref_score >= 50` and title similarity >= 0.80 and (year or author matches) → accept.
- Otherwise → reject with `error = "no confident CrossRef match"`.

### 4. Extract PDF / OA hints

From the selected work, check in this order:

1. `link[].URL` where `content-type == "application/pdf"` → direct PDF
2. `link[].URL` where `intended-application == "text-mining"` → often OA PDF
3. `URL` field → landing page; do a light HEAD probe for `citation_pdf_url` meta
4. `resource.primary.URL` → DOI redirect; follow to landing page

Do not spider the publisher site. If no direct PDF is obvious, return `oa_status: False` and let the caller try Unpaywall or CORE.

### 5. Download PDF (optional)

If a direct PDF URL was found:

```
GET {pdf_url}
User-Agent: survey-agent/1.0 (mailto:YOUR_EMAIL)
Accept: application/pdf
```

Validate `Content-Type: application/pdf` and size >= 10 KB. Retry up to 2 times with 10s backoff on `403`, `429`, or `5xx`.

## Fallback chain

If CrossRef fails:

1. Try DOI directly via `https://doi.org/{doi}` redirect.
2. CORE API `/v3/search/works`.
3. Unpaywall: `https://api.unpaywall.org/v2/{doi}?email=...`
4. Semantic Scholar title search.
5. arXiv title search.

Record the first successful source in the DB.

## Integration points

| Stage | File | Usage |
|-------|------|-------|
| `s00_harvest` | `src/agent_survey/services/dblp.py` | Backfill missing DOIs |
| `s01_enrich` | `src/agent_survey/stages/s01_enrich/__init__.py` | Fallback metadata + abstract hints |
| `s03_survey_mining` | `src/agent_survey/stages/s03_survey_mining/download.py` | Resolve DOI → publisher PDF before CORE/Unpaywall |
| `report` | `src/agent_survey/report/markdown.py` | Canonicalize citation metadata |

## Why these choices

- **CrossRef as authority**: CrossRef is the canonical source for DOI metadata; S2 sometimes normalizes titles differently. It is especially useful for non-CS journals.
- **`mailto` on every request**: This is the single biggest reliability improvement; without it you share the unregistered pool and risk `503 Slow Down`.
- **Not a PDF host**: CrossRef indexes links but does not host PDFs. Many links are paywalled, so always pair CrossRef with Unpaywall or CORE for OA status.
- **`rows=5`**: Title searches often return near-duplicates (preprint + version of record). Top-5 is enough; higher values waste quota.

## Example

Input:

```json
{
  "title": "Advancing Static Analysis in LLM-Based Code Generation: A Survey",
  "year": 2025,
  "doi": null
}
```

Flow:

1. Search: `GET /works?query.title=...&rows=5&mailto=me@example.com`
2. Pick item with score 28.5, title similarity 0.94, year 2025 → accept.
3. Canonical DOI: `10.1007/s10664-025-10555-x`, publisher: Springer Nature.
4. CrossRef `link[]` has no direct PDF → `oa_status: False`.
5. Fallback: pass DOI to Unpaywall → returns OA PDF URL → download succeeds.

## Error catalog

| Error | Meaning | Action |
|-------|---------|--------|
| `503 Slow Down` | Rate limit / polite-pool pressure | Sleep 10s; reduce to 1 req/s |
| `404 Not Found` | DOI not in CrossRef | Fallback to title search |
| `0 items returned` | Title not indexed | Try CORE or Unpaywall |
| `score < threshold` | Candidates exist but none confident | Log for manual review |
| `link URL is paywall` | PDF link requires subscription | Try Unpaywall `is_oa=true` |
| `DOI resolves to unrelated paper` | Bad input DOI | Ignore input DOI; do title search |
