# Playwright Non-Headless Paper Search Agent — Requirements Spec

**Status**: draft  
**Author**: survey_agent team  
**Purpose**: Hand this spec to Claude Code (or another agent) for implementation.  

---

## 1. Problem Statement

Current API-only paper resolution fails when:
- arXiv / Semantic Scholar / OpenReview rate-limit or blacklist the exit IP.
- The paper has no arXiv preprint (common for CHI, FSE, ICSE, IEEE S&P, Springer journals).
- The only public metadata is on a publisher HTML page or Google Scholar index.

Headless Playwright is easily detected by Google Scholar and some publisher CDNs.  
**Solution**: run Playwright in **non-headless** mode with strong human-behavior mimicry, so the browser appears to be a real user doing manual research.

---

## 2. Goal

Build a reusable `playwright_search_agent` module that, given a paper title (and optionally authors / year / venue), can search multiple web channels and return the best-available:

- `pdf_url` — direct PDF link if found
- `landing_url` — official paper page
- `doi` — DOI if displayed
- `abstract` — abstract text if extractable from page
- `source` — which channel succeeded
- `confidence` — `high` / `medium` / `low` based on title match + domain trust

---

## 3. Search Channels (MVP)

| Priority | Channel | Why use it | Risks |
|----------|---------|-----------|-------|
| 1 | **arXiv search** (`arxiv.org/search`) | Highest success rate for AI/ML papers; no paywall | Rate limits; may not have SE/security papers |
| 2 | **OpenReview search** (`openreview.net/search`) | ICLR/ICML/NeurIPS official source | Requires login/token for some forums; anti-bot |
| 3 | **Google Scholar** (`scholar.google.com`) | Best coverage across all venues | Aggressively blocks bots; needs non-headless + human delays |
| 4 | **Publisher page probe** (ACM DL, IEEE Xplore, Springer) | Last resort for paywalled venues | Paywalls, CAPTCHAs, TOS restrictions — only extract metadata/DOI, do NOT bypass paywall |

**Future channels**: Semantic Scholar web UI, CORE web UI, ACL Anthology search, DBLP landing pages.

---

## 4. Anti-Detection Requirements

### 4.1 Browser launch
- **Must use non-headless**: `chromium.launch(headless=False)`.
- Use a normal viewport (e.g., 1440×900 or 1920×1080), not the headless default 800×600.
- Optionally inject `navigator.webdriver = false` via `add_init_script`, but non-headless is the primary defense.

### 4.2 Human-like interaction
- Randomized typing speed (30–120 ms per keystroke) with occasional backspaces.
- Randomized mouse movement before clicks; clicks inside the input/button bounding box with small jitter.
- Scrolling with variable speed and occasional pauses.
- Wait for natural page events (`domcontentloaded` or specific selector), never `networkidle` on search pages.

### 4.3 Pacing & session
- **Global rate limit**: max 1 search every 8–15 seconds, randomized.
- **Per-channel daily budget**: e.g., Google Scholar ≤ 30 queries/session, arXiv ≤ 100.
- Persist cookies / localStorage across sessions (optional) to avoid cold-start bot profiling.
- Rotate User-Agent per channel launch (keep a small list of real desktop Chrome UA strings).

### 4.4 Failure handling
- If a page returns CAPTCHA or "unusual traffic" warning, **abort immediately**, log the event, and move to next channel.
- Never retry the same channel within the same session once blocked.
- Respect `robots.txt` and `403` responses.

---

## 5. Input / Output Contract

### Input
```python
{
    "title": "str — required",
    "authors": ["str"] — optional,
    "year": int — optional,
    "venue": "str — optional",
    "preferred_channels": ["arxiv", "openreview", "scholar", "publisher"],  # default all
}
```

### Output
```python
{
    "success": bool,
    "source": "arxiv_search|openreview_search|google_scholar|publisher_page",
    "confidence": "high|medium|low",
    "title_matched": "exact|fuzzy|none",
    "pdf_url": "str|None",
    "landing_url": "str|None",
    "doi": "str|None",
    "abstract": "str|None",
    "metadata": {
        "authors": [...],
        "year": int,
        "venue": str,
    },
    "logs": [
        {"channel": "arxiv", "status": "success", "latency_ms": 2340},
        {"channel": "scholar", "status": "blocked_by_captcha", "latency_ms": 5600},
    ]
}
```

---

## 6. Per-Channel Procedure

### 6.1 arXiv search
1. Go to `https://arxiv.org/search/?query=<title>&searchtype=title&source=header&order=-announced_date_first`.
2. Wait for `.arxiv-result` or `.no-results`.
3. Extract first result title + authors + link.
4. Fuzzy title match ≥ 0.85 → click result → extract `pdf_url` from `a[href*="/pdf/"]` or meta tag.

### 6.2 OpenReview search
1. Go to `https://openreview.net/search?id=&term=<title>&content=all&group=all&source=all`.
2. Wait for search results list.
3. Click first matching forum.
4. Extract abstract from page content or API call (`/notes?id=...`).
5. PDF is often at `https://openreview.net/forum?id=XXX` → click PDF button or infer `pdf?id=XXX`.

### 6.3 Google Scholar
1. Go to `https://scholar.google.com/scholar?q=<title>`.
2. Type slowly into the search box (if not already on results page).
3. Wait for `#gs_res_ccl_mid` or `.gs_r`.
4. Extract first result:
   - Title from `h3 a`
   - Landing URL from `h3 a@href`
   - PDF link from `[data-lid] a[href$=".pdf"]` or `.gs_or_ggsm a`
5. If result has `[PDF]` label on the right, use that direct link.
6. **Stop condition**: if page shows "Please show you're not a robot" or connection closed → abort Scholar for this session.

### 6.4 Publisher page probe (fallback)
1. Use landing_url from Scholar/S2/Crossref if available.
2. Open page with Playwright non-headless.
3. Extract from HTML meta tags (priority):
   - `<meta name="citation_abstract">`
   - `<meta name="citation_pdf_url">`
   - `<meta name="citation_doi">`
   - `<meta property="og:description">` (fallback abstract)
4. Do **not** attempt to bypass paywalls.  
   If PDF requires institutional login, return `pdf_url: None` and `landing_url` + `doi` + `abstract`.

---

## 7. Test Dataset (10 Papers)

Use this dataset to validate the implementation.  
For papers with an arXiv link, the agent should find the PDF through arXiv search.  
For papers without an arXiv link, the agent should find metadata (and optionally a free PDF) through Scholar / OpenReview / publisher page.

### 7.1 Group A — Papers with known arXiv links (expected: arXiv succeeds)

Sourced from `automated-research` topic in `output/db/papers.sqlite`.

| # | Title | Venue | Year | arXiv ID | Expected source |
|---|-------|-------|------|----------|-----------------|
| A1 | ScienceAgentBench: Toward Rigorous Assessment of Language Agents for Data-Driven Scientific Discovery | ICLR | 2025 | 2410.05080 | arXiv |
| A2 | Can LLMs Generate Novel Research Ideas? A Large-Scale Human Study with 100+ NLP Researchers | ICLR | 2025 | 2409.04109 | arXiv |
| A3 | CycleResearcher: Improving Automated Research via Automated Reviewing | ICLR | 2025 | 2411.00816 | arXiv |
| A4 | SURVEYFORGE: On the Outline Heuristics, Memory-Driven Generation, and Multi-dimensional Evaluation for Automated Survey Writing | ACL | 2025 | 2503.04629 | arXiv |
| A5 | Completing A Systematic Review in Hours instead of Months with Interactive AI Agents | ACL | 2025 | 2504.14822 | arXiv |

### 7.2 Group B — Papers without arXiv (expected: Scholar / OpenReview / publisher succeeds)

Sourced from `automated-research` topic in `output/db/papers.sqlite`. These have DOI or official venue URLs but no arXiv preprint in our DB.

| # | Title | Venue | Year | DOI / Official URL | Expected source |
|---|-------|-------|------|-------------------|-----------------|
| B1 | ARCHE: A Novel Task to Evaluate LLMs on Latent Reasoning Chain Extraction | AAAI | 2026 | `10.1609/aaai.v40i3.37170` | Google Scholar → AAAI |
| B2 | Automatic Paper Reviewing with Heterogeneous Graph Reasoning over LLM-Simulated Reviewer-Author Debates | AAAI | 2026 | `10.1609/aaai.v40i37.40439` | Google Scholar → AAAI |
| B3 | Deep Research Arena: The First Exam of LLMs' Research Abilities via Seminar-Grounded Tasks | AAAI | 2026 | `10.1609/aaai.v40i39.40620` | Google Scholar → AAAI |
| B4 | SoK: Automated Vulnerability Repair: Methods, Tools, and Assessments | USENIX Security | 2025 | `https://www.usenix.org/conference/usenixsecurity25/presentation/hu-yiwei` | Google Scholar → USENIX |
| B5 | SoK: Towards Effective Automated Vulnerability Repair | USENIX Security | 2025 | `https://www.usenix.org/conference/usenixsecurity25/presentation/li-ying` | Google Scholar → USENIX |

> **Note**: If a Group B paper is later found to have an arXiv preprint, treat it as a bonus success but the **primary success criterion** is finding the official landing URL + DOI/abstract.

---

## 8. Success Criteria

For each test paper, evaluate:

| Criterion | Required for | Points |
|-----------|--------------|--------|
| Returns within 60s | All | must |
| Title match ≥ 0.85 | All | must |
| `landing_url` resolved | All | must |
| `pdf_url` resolved | Group A only | 5/5 must pass |
| `abstract` extracted | All | nice-to-have for Group B |
| No CAPTCHA / block during full test run | All | must |
| Logs every channel attempt with status | All | must |

**Target**: 10/10 `landing_url` resolved, 5/5 Group A PDF downloaded, 0 CAPTCHA triggers.

---

## 9. Non-Goals & Constraints

- **Do NOT bypass paywalls** or institutional logins.  Extract metadata only from publisher pages.
- **Do NOT mass-scrape Google Scholar**.  Stay within polite human query volumes (≤ 30/session, spaced).
- **Do NOT store PDFs** in this module; return URLs only.  Downloader is a separate stage.
- **Do NOT run headless** for Google Scholar.  Headless is acceptable only for arXiv/OpenReview if non-headless proves unstable.

---

## 10. Suggested File Layout

```
src/agent_survey/services/
├── playwright_search/
│   ├── __init__.py
│   ├── agent.py           # main orchestrator
│   ├── channels/
│   │   ├── arxiv.py
│   │   ├── openreview.py
│   │   ├── scholar.py
│   │   └── publisher.py
│   ├── humanize.py        # typing, mouse, scroll randomization
│   └── match.py           # title similarity + confidence scoring
```

---

## 11. CLI / Debug Hook

Add a CLI command for manual testing:

```bash
survey_agent test-search \
  --title "AutoSurvey: Large Language Models Can Automatically Write Surveys" \
  --channels arxiv,scholar \
  --visible
```

`--visible` forces `headless=False` so the operator can watch the browser.

---

## 12. Open Questions for Implementer

1. Should we maintain a persistent browser context (cookies/localStorage) across queries, or launch fresh per paper?
2. Do we need a proxy toggle per channel in `config/network.yaml`?
3. Should failed/blocked channels be cached in a local JSON file to skip on next run?
4. Do we integrate this into `s03_survey_mining` download fallback, or keep it as a standalone `s08_fulltext` fallback?
