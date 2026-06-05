"""
Skill: source_probe
===================
Quickly test whether a data source can serve a specific venue-year.

When to use
-----------
- Before committing to a full harvest/enrich run for a new venue
- When a source (DBLP, S2, OpenReview) starts returning errors
- To verify a proxy configuration is working

Procedure
---------
1. Select N random papers from the target venue-year (default N=5)
2. For each paper, query the source and check:
   - Response time (flag if > 5s)
   - HTTP status (flag if not 200)
   - Data quality (abstract length ≥ 30, title match ≥ 0.75)
3. Report: success_rate, avg_latency, failure_modes
4. Decision:
   - success_rate ≥ 0.8 → source is healthy
   - 0.5 ≤ success_rate < 0.8 → source is flaky (retry with backoff)
   - success_rate < 0.5 → source is down or incompatible — skip it

Supported sources
-----------------
- ``dblp_toc`` — DBLP XML Table of Contents
- ``dblp_search`` — DBLP Search API (venue:XXX year:YYYY)
- ``s2`` — Semantic Scholar title search
- ``arxiv`` — arXiv API title search
- ``openreview_v1`` — OpenReview v1 notes/search
- ``openreview_forum`` — OpenReview forum ID direct lookup
- ``aclanthology`` — ACL Anthology page scraping
- ``crossref`` — Crossref DOI API
- ``playwright_conf`` — conf.researchr.org via headless browser

Example
-------
    probe("iclr", 2024, source="openreview_forum")
    → {"ok": 5, "total": 5, "avg_ms": 350, "healthy": True}

    probe("fse", 2024, source="dblp_toc")
    → {"ok": 0, "total": 5, "avg_ms": 1200, "healthy": False,
       "errors": ["HTTP 404 for all attempts"]}
"""

SKILL = {
    "name": "source_probe",
    "version": "1.0",
    "category": "adapt",
    "description": "Quick health check of a data source for a venue-year",
    "trigger": "Source returns errors or a new venue needs source selection",
    "inputs": {
        "venue_name": "str",
        "year": "int",
        "source": "str — source identifier from supported list",
        "sample_size": "int — default 5",
        "proxy": "str | None — http://host:port",
    },
    "outputs": {
        "healthy": "bool",
        "success_rate": "float",
        "avg_latency_ms": "float",
        "errors": "list[str] — failure descriptions",
    },
    "thresholds": {
        "healthy": 0.8,
        "flaky": 0.5,
        "max_latency_ms": 5000,
        "min_abstract_chars": 30,
    },
}
