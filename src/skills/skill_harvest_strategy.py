"""
Skill: harvest_strategy
=======================
Develop a per-venue, per-year paper harvest strategy.

When to use
-----------
- Adding a new venue (conference or journal) to the survey
- An existing venue's harvest returns 0 papers or errors out
- DBLP changes its HTML/XML structure for a venue
- A venue switches to a new proceedings host (e.g., OpenReview → ACM)

Procedure (incremental, one venue at a time)
---------------------------------------------
1.  **Probe DBLP XML TOC**
    Try: ``https://dblp.org/db/conf/<abbrev>/<abbrev>{year}.xml``
    - If HTTP 200 + ``<inproceedings>`` elements found → *strategy: xml_toc*
    - If 404 → go to step 2
    - If 200 but empty <inproceedings> → check if venue uses multi-volume (e.g., AAAI-1, AAAI-2)

2.  **Derive TOC path from key_prefixes**
    Use the venue's DBLP key prefix (e.g., ``conf/sigsoft/`` → ``conf/sigsoft/fse``)
    - If that path works → *strategy: xml_toc (derived)*
    - If not → go to step 3

3.  **Try DBLP Search API**
    Query: ``venue:{name} year:{year}``
    - If returns papers with correct key_prefixes → *strategy: search_api*
    - If timeout/500 → go to step 4

4.  **Try Playwright on official website**
    Use ``conf.researchr.org`` or venue-specific URL.
    - Load page with ``wait_until=domcontentloaded``
    - Wait for ``[id*='event'] table tbody tr`` selector (max 8s)
    - Extract: title from ``td a[data-event-modal]``, authors from ``.performers a``
    - If ≥ 10 papers found → *strategy: playwright*

5.  **Mark as unresolvable**
    If all steps fail, mark venue-year as ``failed`` and log the error.
    A human should manually verify the venue exists and provide a custom URL.

Decision rules
--------------
- If strategy A works for venue X, try it first for venue Y
- If it fails, develop a **new strategy** specific to Y — don't force-fit
- Overrides live in ``stages/s00_harvest/strategies/__init__.py`` → ``VENUE_PLAYWRIGHT_URLS``
- The override table is the system's **accumulated knowledge**

Validation
----------
- Each venue-year should have paper counts within ±15% of known acceptance numbers
- Cross-check against official proceedings pages or DBLP index
- Empty results for years ≤ current_year-1 need investigation

Integration points
------------------
- ``stages/s00_harvest/core.py`` → ``_fetch_adaptive()``
- ``stages/s00_harvest/strategies/playwright_fetcher.py``
- ``services/harvest_strategies.py`` → venue override table
"""

SKILL = {
    "name": "harvest_strategy",
    "version": "1.0",
    "category": "harvest",
    "description": "Develop per-venue harvest strategy via incremental probing",
    "trigger": "A venue-year returns 0 papers or harvest errors out",
    "inputs": {
        "venue_name": "str — conference/journal name (e.g., 'FSE', 'TOSEM')",
        "year": "int — target year",
        "venue_config": "VenueCfg — key_prefixes, aliases, skip_years, toc_stream",
    },
    "outputs": {
        "strategy": "str — one of: xml_toc | search_api | playwright | json_source",
        "source_url": "str | None — TOC URL or Playwright URL",
        "paper_count": "int — number of papers extracted (validation)",
    },
    "steps": [
        "probe_xml_toc",
        "derive_from_key_prefixes",
        "try_search_api",
        "try_playwright_official_site",
    ],
    "fallback_chain": [
        "xml_toc",
        "search_api (15s timeout)",
        "playwright (conf.researchr.org)",
    ],
}
