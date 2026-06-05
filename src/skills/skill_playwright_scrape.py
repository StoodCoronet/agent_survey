"""
Skill: playwright_scrape
========================
Adaptive headless-browser scraping with selector auto-discovery.

When to use
-----------
- A venue's proceedings page is JavaScript-rendered (no static HTML)
- API endpoints are down or don't cover the venue
- DBLP hasn't indexed a recent conference year yet
- Need to extract paper title + authors + abstract from a conference site

Procedure
---------
1. **Load page with minimal wait**
   - Use ``wait_until=domcontentloaded`` (NOT ``networkidle`` — saves 20-30s)
   - Wait for a known content selector (max 8s)
   - If page doesn't load → try with proxy; if still fails → give up

2. **Auto-discover selectors**
   Try these in order, stopping at the first that yields ≥ 5 results:
   - ``[id*='event'] table tbody tr`` → conf.researchr.org
   - ``.paper .paper-title``, ``.paper a[data-event-modal]`` → various
   - ``.card .card-title`` → mini-conf (COLM, etc.)
   - ``h4:has(+ .authors)`` → generic
   If no selector works → try step 3

3. **Analyze page structure**
   - Dump all CSS classes containing "paper", "event", "title", "abstract"
   - Dump all ``<h4>``, ``<h3>``, ``<a>`` elements with long text
   - Ask agent to identify paper container pattern
   - Add discovered selector to selector registry

4. **Extract metadata per paper**
   - Title: ``td a[data-event-modal]`` or ``.paper-title``
   - Authors: ``.performers a`` or ``.paper-authors``
   - DOI: ``a[href*='doi.org']``
   - Abstract: click modal → ``.modal-body`` or ``meta[name='citation_abstract']``

5. **Persist strategy**
   - Add URL + working selectors to ``VENUE_PLAYWRIGHT_URLS``
   - This avoids re-discovering selectors on subsequent runs

Selector registry
-----------------
Venue-specific selectors are stored in:
``stages/s00_harvest/strategies/__init__.py → VENUE_PLAYWRIGHT_URLS``

Known working patterns:
- conf.researchr.org: ``table tbody tr``, title in ``a[data-event-modal]``
- colmweb mini-conf: JSON endpoint at ``serve_papers.json``
- OpenReview forum: v1 API at ``api.openreview.net/notes?forum={id}``

Tuning
------
- ``wait_until``: ``domcontentloaded`` (fast) vs ``networkidle`` (slow, avoids missing lazy content)
- ``sleep_after_load``: 1-4s depending on JS complexity
- ``proxy``: auto-injected from ``config.http_proxy``
"""

SKILL = {
    "name": "playwright_scrape",
    "version": "1.0",
    "category": "adapt",
    "description": "Adaptive headless-browser scraping with selector discovery",
    "trigger": "Static HTTP fails and page content is JavaScript-rendered",
    "inputs": {
        "url": "str — target proceedings page",
        "venue_name": "str",
        "year": "int",
        "proxy": "str | None",
        "selector_override": "str | None — use this selector instead of auto-discovery",
    },
    "outputs": {
        "papers": "list[dict] — extracted paper metadata",
        "selector_used": "str — which CSS selector worked",
        "load_time_ms": "float",
    },
    "selector_candidates": [
        "[id*='event'] table tbody tr",
        ".paper a[data-event-modal]",
        ".card .card-title",
        "h4:has(+ .authors)",
        "[class*='paper'] h4",
    ],
    "known_sites": {
        "conf.researchr.org": "table tbody tr → a[data-event-modal] (title) + .performers a (authors)",
        "colmweb.org": "/serve_papers.json (API)",
        "aclanthology.org": "div.acl-abstract span (static, no JS needed)",
        "openreview.net": "/notes/search (v1 API) or /notes?forum={id}",
    },
}
