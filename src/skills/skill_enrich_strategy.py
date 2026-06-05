"""
Agent-executable skill: develop per-venue abstract acquisition strategy.

This skill is a PLAYBOOK for an AI agent.  The agent follows these steps
autonomously: probe sources, evaluate results, make decisions, persist changes.
"""

SKILL = {
    "name": "enrich_strategy",
    "version": "1.0",
    "role": "agent_playbook",
    "trigger": "User says: 'enrich strategy for <venue>' OR abstract coverage < 80% after enrich pass OR new venue added",
    "goal": "Find the optimal set of abstract sources for a venue, achieving ≥90% coverage with minimal overhead",
}

# ── Phase 1: Probe (10 papers, find working sources) ──────────────

# KEY INSIGHT: Always probe fast HTTP sources (meta tags, page HTML) BEFORE
# slow API/Playwright sources.  Many venues have abstracts in static HTML
# accessible with plain httpx at 50+ RPS — 10-50x faster than S2 or Playwright.

PROBE_STEPS = [
    {
        "step": 1,
        "name": "sample_papers",
        "action": "Query 10 random papers from the venue with missing abstracts",
        "command": """sqlite3 output/db/papers.sqlite \\
  "SELECT paper_id, title, doi, url, dblp_key FROM papers \\
   WHERE venue='{venue}' AND (abstract IS NULL OR abstract='') \\
   ORDER BY RANDOM() LIMIT 10" """,
        "output": "List of 10 paper dicts with title, doi, url",
        "priority": "ALWAYS FIRST — cheap but high-yield for open-access venues",
    },
    {
        "step": 2,
        "name": "probe_http_meta",
        "action": "Check paper page HTML for abstract in meta tags or body structure",
        "priority": "ALWAYS SECOND — faster than any API (50+ RPS).  Do this BEFORE s2.",
        "code": """# 2a. Check <meta> tags (server-side rendered content):
#   <meta name="citation_abstract" content="...">   ← OpenReview, many publishers
#   <meta name="description" content="...">          ← PMLR, many publishers
#   <meta property="og:description" content="...">   ← universal fallback
curl -sL "$PAPER_URL" | grep -o 'citation_abstract\|og:description\|description'

# 2b. Check page body for known structures:
#   OpenReview: "Abstract:" visible text (16/20 papers)
#   NeurIPS proceedings.neurips.cc: <p class="paper-abstract">
#   ACL Anthology: <div class="acl-abstract"><span>
#   PMLR: <meta name="description" content="...">  (10/10 papers)

# 2c. If the paper URL points to a DIFFERENT domain than the abstract host,
#     follow redirects or construct the right URL:
#   NeurIPS: papers.nips.cc → proceedings.neurips.cc (same path, https)
#   ACL: doi.org/10.18653/... → aclanthology.org/{id}/ (construct from DOI)""",
        "decision": "if ≥90% have abstracts via HTTP → use ['meta'] only.  If 50-90% → use ['meta', 's2'].  If <50% → meta is supplementary, s2 is primary.",
        "examples": {
            "ICLR": "citation_abstract meta tag in OpenReview HTML → ['meta'], 50+ RPS",
            "ICML": "description meta tag in PMLR HTML → ['meta'], 50+ RPS",
            "NeurIPS": "p.paper-abstract in proceedings.neurips.cc → ['meta'], 50+ RPS",
            "CHI": "ACM paywall blocks HTML access → skip meta, use ['s2']",
        },
    },
    {
        "step": 3,
        "name": "probe_s2",
        "action": "Test each paper against Semantic Scholar API",
        "trigger": "Only if HTTP meta coverage < 90%",
        "code": """from agent_survey.services.s2 import S2Client
s2 = S2Client(api_key=cfg.semantic_scholar_api_key, timeout=15)
for paper in papers:
    data = s2.search_by_title(paper['title'])
    ok = data and len(data.get('abstract','').strip()) >= 30
    sleep(0.3)""",
        "note": "Slow (1 RPS).  Use only as fallback or for paywalled venues.",
    },
    {
        "step": 4,
        "name": "probe_arxiv",
        "action": "Test papers via arXiv API",
        "code": """from agent_survey.services import arxiv as arxiv_src
ax = arxiv_src.search_title(http, title)
ok = ax and len(ax.get('abstract','').strip()) >= 30""",
    },
    {
        "step": 4,
        "name": "probe_openreview_v1",
        "action": "Test via OpenReview v1 notes/search API (fuzzy title match)",
        "code": """from agent_survey.services.openreview import search_title
result = search_title(http, title)
ok = result and len(result.get('abstract','').strip()) >= 30""",
        "decision": "If ≥ 0.5 but < 0.9 → keep as supplementary source. If < 0.5 → skip OpenReview for this venue.",
    },
    {
        "step": 5,
        "name": "probe_openreview_forum_id",
        "action": "For papers with openreview.net/forum?id=XXX URLs, direct API lookup",
        "trigger": "Only if step 4 had low yield AND papers have forum URLs",
        "code": """import re
fid = re.search(r'forum\?id=([\w_-]+)', url).group(1)
r = http.get(f'https://api.openreview.net/notes?forum={fid}')
for note in r.json().get('notes', []):
    abst = note['content'].get('abstract','')
    if isinstance(abst, dict): abst = abst.get('value','')
    if len(abst) >= 50: return abst""",
    },
    {
        "step": 6,
        "name": "probe_aclanthology",
        "action": "For venues on ACL Anthology, scrape abstract from paper page",
        "trigger": "Only for EMNLP, NAACL, ACL, EACL, AACL, COLING, *CL venues",
        "code": """from .strategies.aclanthology import fetch_aclanthology_abstract
text = fetch_aclanthology_abstract(http, url)
ok = text is not None and len(text) >= 30""",
    },
    {
        "step": 7,
        "name": "probe_crossref",
        "action": "For papers with DOIs, try Crossref API",
        "trigger": "If paper has a DOI field",
        "code": """from .strategies.crossref import fetch_crossref_abstract
text = fetch_crossref_abstract(http, doi)
ok = text is not None and len(text.strip()) >= 30""",
    },
    {
        "step": 8,
        "name": "probe_html_meta",
        "action": "Check if abstract is in server-side HTML meta tags (SEO content)",
        "trigger": "Page is JS-rendered (React/Vue/etc.) but may have SSR content",
        "code": """# Many JS-rendered sites embed abstract in meta tags for SEO:
#   <meta name="citation_abstract" content="...">
#   <meta name="description" content="...">
#   <meta property="og:description" content="...">
# This is 10-50x faster than Playwright — pure httpx, no browser.

curl -sL "https://openreview.net/forum?id=XXX" | grep citation_abstract""",
        "decision": "If meta tag found → skip Playwright, use httpx + regex",
        "note": "ALWAYS check this before resorting to Playwright.  OpenReview, ACL Anthology, IEEE, and many others have SSR abstracts.",
    },
    {
        "step": 9,
        "name": "probe_playwright",
        "action": "Last resort — headless browser on official proceedings site",
        "trigger": "If no meta tag AND all HTTP sources combined still < 0.9",
        "code": """# Launch Playwright, load page with domcontentloaded (not networkidle!)
# Try selectors: [id*='event'] table tr, .paper .paper-title, .card-title
# Try text matching: wait for 'Abstract:' text, extract following paragraph
# Timeout per paper: 15s""",
        "note": "Heavyweight (~1s per paper with shared browser). Only for venues with no API/SSR coverage.",
    },
]

# ── Phase 2: Decide ────────────────────────────────────────────────

DECISION_RULES = """
After probing, rank sources by success rate.  Build the final source list.

CRITICAL: Always prioritize fast HTTP sources over slow API/Playwright sources:
  meta > aclanthology > crossref > s2 > playwright

1. If HTTP meta achieves ≥ 0.9 → use ['meta'] only (50+ RPS, no API key needed)
2. If meta + s2 complement to ≥ 0.9 → use ['meta', 's2']
3. If venue-specific scraper works (aclanthology, crossref) → use it before meta
4. If even playwright fails → mark venue as 'needs_manual_review'

The final source list replaces the generic fallback chain.
Update enrich_config.yaml → venue_strategies.
"""

# ── Phase 3: Persist ───────────────────────────────────────────────

PERSIST_ACTION = {
    "file": "src/agent_survey/stages/s01_enrich/sources.py",
    "field": "_VENUE_SOURCES",
    "example": '"ICLR": ["s2", "openreview_forum"],  # 90% probe: s2 60% + forum 30%',
    "note": "Also add any new strategy files under strategies/ if a new source type was created",
}

# ── Phase 4: Post-run gap analysis ──────────────────────────────────

POST_RUN = {
    "trigger": "After FULL enrich completes for the venue",
    "steps": [
        {
            "step": "query_failures",
            "sql": """SELECT venue, enrich_source, COUNT(*) as n, year
FROM papers WHERE venue='{venue}' AND (abstract IS NULL OR abstract='')
GROUP BY venue, enrich_source, year
HAVING n >= 5
ORDER BY n DESC""",
            "purpose": "Cluster remaining failures by (venue, source, year)",
        },
        {
            "step": "diagnose_cluster",
            "action": "For each failure cluster with n ≥ 5, sample 3 papers and manually check:",
            "checks": [
                "Is the source still up? (curl the endpoint)",
                "Did the URL format change? (e.g. trailing slash, new path pattern)",
                "Is the paper behind a new paywall?",
                "Is this a specific year that uses a different platform?",
                "Are these actually papers? (Check title — maybe proceedings/editorial)",
            ],
        },
        {
            "step": "decide_action",
            "options": {
                "extend_existing": "Fix regex/URL in existing strategy (e.g. aclanthology.py)",
                "add_fallback": "Add a new source to _VENUE_SOURCES for this venue",
                "add_playwright": "Add a Playwright URL to VENUE_PLAYWRIGHT_URLS",
                "mark_unresolvable": "These are not real papers (proceedings volumes etc.) — mark in DB",
            },
        },
        {
            "step": "apply_and_retry",
            "action": "Apply the fix, re-run enrich for just this venue's failed papers, re-check coverage",
        },
    ],
    "iteration_goal": "Each gap-analysis cycle should reduce missing abstracts by ≥ 50%",
    "stop_condition": "Coverage ≥ 98% OR remaining failures are all non-papers (proceedings, editorials, errata)",
}

# ── Complete workflow ───────────────────────────────────────────────

WORKFLOW = """
1. User: "enrich strategy for <venue>"
2. Agent executes PROBE_STEPS sequentially, stopping early if ≥ 0.9 found
3. Agent reports: "Best strategy for <venue>: [s2, aclanthology] (92% probe, 2.3s avg)"
4. Agent edits sources.py to update _VENUE_SOURCES
5. Agent: "Ready. Run `survey_agent enrich` to apply."
6. User runs full enrich
7. Agent runs POST_RUN gap analysis
8. Agent diagnoses failure clusters, proposes fixes
9. Agent applies fixes, user re-runs enrich
10. Repeat 7-9 until coverage ≥ 98%
"""
