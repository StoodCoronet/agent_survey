# External APIs & Keys Reference

Last updated: 2026-06-06

## Current Key Inventory

| Service | Has Key | Config Key | Rate Limit (no key) | Rate Limit (with key) | Notes |
|---------|---------|------------|---------------------|-----------------------|-------|
| **DeepSeek** | ✅ | `DEEPSEEK_API_KEY` | Paid API, no free tier | Same | Already configured |
| **Semantic Scholar** | ✅ | `SEMANTIC_SCHOLAR_API_KEY` | ~1 req/s | ~100 req/s | Already configured |
| **arXiv** | ❌ | — | ~3s between requests | Same | Open API, no key |
| **OpenReview** | ❌ | — | Low (unauthenticated) | Higher with login | Can generate API token after login |
| **CrossRef** | ❌ | — | "Polite" pool | Higher with registered email | Recommend adding `mailto=` param |
| **Unpaywall** | ❌ | — | 100k requests/day | Same | Requires email in request |
| **DBLP** | ❌ | — | Unknown | — | No key needed |
| **ACL Anthology** | ❌ | — | Unknown | — | No key needed |

---

## Recommended Key Applications

### 1. Semantic Scholar (already have — verify & upgrade)
- **Current status**: Have basic key (`s2k-...`)
- **Benefit of upgrading**: Partner API offers higher throughput
- **Apply**: https://www.semanticscholar.org/product/api
- **Action**: Verify current key is active; apply for Partner API if we hit 100 req/s limit

### 2. OpenReview API Token
- **Why**: Download PDFs from ICLR/ICML/NeurIPS without browser fallback
- **Rate limit lift**: Authenticated requests get higher quota
- **Apply**: https://openreview.net/profile → API Tokens
- **Config**: Add `OPENREVIEW_API_KEY` to `.env`

### 3. CORE API (new — highly recommended)
- **Why**: Find OA (Open Access) PDFs for papers not on arXiv
- **Coverage**: 200M+ research papers
- **Apply**: https://core.ac.uk/services/api (free tier: 10k requests/month)
- **Config**: Add `CORE_API_KEY` to `.env`
- **Use case description** (copy/paste for application form, 98 chars):
  ```
  Using CORE to discover open-access research papers and enrich metadata for a literature survey tool.
  ```

### 4. CrossRef "Polite" Registration
- **Why**: Higher priority pool, faster responses
- **How**: Register email at https://www.crossref.org/services/metadata-delivery/
- **Usage**: Append `mailto=your@email.com` to all CrossRef requests
- **No formal key**, just email registration

---

## APIs That Don't Need Keys (but have best practices)

| Service | Best Practice |
|---------|--------------|
| arXiv | Wait 3s between requests; use `export.arxiv.org` not `arxiv.org` for API |
| Unpaywall | Always include `email=` param in requests |
| DBLP | Respect robots.txt; cache aggressively |
| ACL Anthology | Use their BibTeX/XML endpoints; don't scrape HTML |

---

## Integration TODO

- [ ] Add `OPENREVIEW_API_KEY` to `config.py` / `.env` loader
- [ ] Add `CORE_API_KEY` to `config.py` / `.env` loader
- [ ] Update `s02_enrich` to use OpenReview token when available
- [ ] Update `s03_survey_mining` download to try CORE API as fallback
