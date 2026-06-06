# Skill: CrossRef Metadata Resolution

## Role
Agent playbook for resolving paper titles / DOIs to authoritative metadata and optional open-access links using the [CrossRef REST API](https://api.crossref.org).

## Trigger
Use this skill when:

- You need a canonical DOI from a free-form title.
- arXiv / S2 / CORE return inconsistent metadata and you want an authoritative reference.
- You need publisher info, page numbers, ISSN, or URL for a harvested paper.
- You are enriching papers from non-CS venues (HCI, IS, SE journals) that are indexed better by CrossRef than by CS APIs.

## Goal
Resolve a paper to its canonical CrossRef work, extract reliable metadata, and opportunistically discover an OA PDF link.

## Inputs

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | str | ✅ unless DOI given | Full title; CrossRef `query.title` works best with complete titles |
| `authors` | list[str] | optional | Family names only are enough; improves ranking |
| `year` | int | optional | Use `filter=from-pub-date:<year>,until-pub-date:<year>` |
| `doi` | str | optional | If known, skip search and call `/works/{doi}` directly |
| `venue_hint` | str | optional | Journal or conference name; can be used to sanity-check results |

## Outputs

| Field | Type | Meaning |
|-------|------|---------|
| `doi` | str \| None | Canonical DOI from CrossRef |
| `title` | str \| None | CrossRef-normalized title |
| `authors` | list[dict] \| None | `[{family, given, affiliation, ORCID}]` |
| `year` | int \| None | Published-print or published-online year |
| `venue` | str \| None | `container-title` (journal) or `publisher` |
| `publisher` | str \| None | Publisher name |
| `page` | str \| None | Page range |
| `volume` / `issue` | str \| None | Journal volume/issue |
| `issn` | list[str] \| None | ISSNs |
| `url` | str \| None | Landing page URL (often `https://doi.org/{doi}`) |
| `pdf_url` | str \| None | OA PDF if linked in `link[content-type=application/pdf]` |
| `oa_status` | bool | Whether CrossRef lists a `link` with `content-type: application/pdf` or `intended-application: text-mining` |
| `score` | float | CrossRef's own `score` field (0–1) or computed fallback |

## Authentication

CrossRef does **not** require an API key, but strongly prefers a registered `mailto` for the "polite" pool.

- Register an email at: https://www.crossref.org/services/metadata-delivery/
- Append `?mailto=YOUR_EMAIL` to **every** request.
- Set `User-Agent` to something descriptive:
  ```
  User-Agent: survey-agent/1.0 (https://your-org.example; mailto:YOUR_EMAIL)
  ```

Without `mailto` you share the "polite" pool with unregistered users and may see slower responses or intermittent blocks.

## Rate Limits

- CrossRef asks for **no more than 50 requests per second** with `mailto`.
- In practice, keep to **5 req/s** to be safe.
- If `503 Slow Down` or `429` is returned, back off to **1 req/s** for 60 seconds.
- Always include `mailto=`; it is the single biggest reliability improvement.

## Procedure

### Step 1 — Direct DOI lookup (if DOI known)

```
GET https://api.crossref.org/works/{doi}?mailto={EMAIL}
```

- Validate JSON `message` exists.
- Extract metadata fields (see Outputs).
- Check `message.link[]` for `content-type: application/pdf` or `intended-application: text-mining`.
- Return immediately.

### Step 2 — Title search

If no DOI:

```
GET https://api.crossref.org/works?query.title={escaped_title}&rows=5&mailto={EMAIL}
```

Best practices:
- URL-encode the title.
- Do **not** wrap in extra quotes; CrossRef's `query.title` already boosts title fields.
- If year known, add filter:
  ```
  &filter=from-pub-date:{year},until-pub-date:{year}
  ```
- If author known, add:
   ```
  &query.author={family_name}
  ```

### Step 3 — Pick best candidate

CrossRef returns `message.items[]` with a `score` field. Evaluate candidates in order:

1. Highest CrossRef `score`.
2. Title similarity `>= 0.85` (rapidfuzz `fuzz.ratio`).
3. Year match (if provided).
4. Author overlap (if provided).

**Decision:**
- `crossref_score >= 80` AND title similarity `>= 0.90` → accept.
- `crossref_score >= 50` AND title similarity `>= 0.80` AND (year or author matches) → accept.
- Otherwise → reject and return `error = "no confident CrossRef match"`.

### Step 4 — Extract PDF / OA hints

From the selected work, check these fields:

```json
{
  "link": [
    {
      "URL": "https://publisher.example/paper.pdf",
      "content-type": "application/pdf",
      "content-version": "vor",
      "intended-application": "text-mining"
    }
  ],
  "resource": {
    "primary": {
      "URL": "https://doi.org/..."
    }
  }
}
```

Priority:
1. `link[].URL` where `content-type == "application/pdf"` → direct PDF
2. `link[].URL` where `intended-application == "text-mining"` → often OA PDF
3. `URL` field → landing page; do light HEAD probe for `citation_pdf_url` meta
4. `resource.primary.URL` → DOI redirect; follow to landing page

If a landing page is reached but no PDF link is obvious, do **not** spider the site. Return `oa_status: False` and let the caller try Unpaywall or CORE.

### Step 5 — Download PDF (optional)

If a direct PDF URL was found:

```
GET {pdf_url}
Headers:
  User-Agent: survey-agent/1.0 (mailto:YOUR_EMAIL)
  Accept: application/pdf
```

- Validate `Content-Type` is `application/pdf`.
- Validate size >= 10 KB.
- On `403` / `429` / `5xx`, retry up to 2 times with 10s backoff.

### Step 6 — Fallback chain

If CrossRef fails:

1. Try DOI directly via `https://doi.org/{doi}` redirect.
2. Try CORE API `/v3/search/works`.
3. Try Unpaywall (`https://api.unpaywall.org/v2/{doi}?email=...`).
4. Try Semantic Scholar title search.
5. Try arXiv title search.

Record the first successful source in DB (`enrich_source` / `download_source`).

## Integration Points

| Stage | File | How to use |
|-------|------|------------|
| `s00_harvest` | `src/agent_survey/services/dblp.py` | Use CrossRef to backfill DOIs missing from DBLP entries |
| `s01_enrich` | `src/agent_survey/stages/s01_enrich/__init__.py` | Fallback for abstract + metadata when S2/arXiv fail |
| `s03_survey_mining` | `src/agent_survey/stages/s03_survey_mining/download.py` | Resolve DOI → publisher PDF link before CORE/Unpaywall |
| `report` | `src/agent_survey/report/markdown.py` | Canonicalize citation metadata (volume, issue, pages) |

## Decision Log

- **Why CrossRef when we already have S2?** CrossRef is the authority for DOI metadata; S2 sometimes has normalized-title mismatches. CrossRef is especially useful for non-CS journals.
- **Why include `mailto=` on every request?** CrossRef explicitly prioritizes registered users; skipping it risks `503 Slow Down`.
- **Why not rely on CrossRef for PDFs?** CrossRef indexes links but does not host PDFs. Many `link[]` entries are publisher paywalls; always pair CrossRef with Unpaywall or CORE for OA status.
- **Why `rows=5`?** Title searches often return near-duplicates (preprint + version of record). Top-5 is enough; higher values waste quota.

## Example Session

```
Input:
  title: "Advancing Static Analysis in LLM-Based Code Generation: A Survey"
  year: 2025
  doi: null

Step 2:
  GET /works?query.title=Advancing%20Static%20Analysis%20in%20LLM-Based%20Code%20Generation%3A%20A%20Survey&rows=5&mailto=me@example.com
  → 3 items

Step 3:
  Item 0: score=28.5, title_similarity=0.94, year=2025 → accept
  → doi: 10.1007/s10664-025-10555-x

Step 4:
  GET /works/10.1007/s10664-025-10555-x?mailto=me@example.com
  → publisher: "Springer Nature"
  → link[] contains URL with content-type "unspecified" → not a direct PDF
  → oa_status: False

Step 6 fallback:
  Pass DOI to Unpaywall → returns OA PDF URL
  → Download succeeds
```

## Error Catalog

| Error | Meaning | Action |
|-------|---------|--------|
| `503 Slow Down` | Rate limit / polite-pool pressure | Sleep 10s, reduce to 1 req/s |
| `404 Not Found` | DOI not in CrossRef | Fallback to title search |
| `0 items returned` | Title not indexed | Try CORE or Unpaywall |
| `score < threshold` | CrossRef found candidates but none confident | Log for manual review |
| `link URL is paywall` | PDF link requires subscription | Try Unpaywall `is_oa=true` |
| `DOI resolves to unrelated paper` | Bad DOI in input | Ignore input DOI, do title search |

## Useful Snippets

### Python: build CrossRef query

```python
from urllib.parse import quote

params = {
    "query.title": title,
    "rows": "5",
    "mailto": email,
}
if year:
    params["filter"] = f"from-pub-date:{year},until-pub-date:{year}"
if authors:
    params["query.author"] = authors[0].split()[-1]  # family name

query = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
url = f"https://api.crossref.org/works?{query}"
```

### Python: extract PDF link from CrossRef work

```python
def extract_pdf_link(work: dict) -> str | None:
    for link in work.get("link", []):
        if link.get("content-type") == "application/pdf":
            return link.get("URL")
    for link in work.get("link", []):
        if link.get("intended-application") == "text-mining":
            return link.get("URL")
    return None
```
