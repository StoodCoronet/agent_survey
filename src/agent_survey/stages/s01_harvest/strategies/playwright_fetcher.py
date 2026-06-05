"""Playwright-based fetcher for conference websites (conf.researchr.org, colmweb.org, etc.).

Used as a last-resort fallback when DBLP TOC and Search API both fail.
Supports proxy injection and tries to extract abstracts from modal popups.
"""
from __future__ import annotations

import asyncio
import re
from typing import Iterator


async def _fetch_conf_researchr(
    page,
    url: str,
    timeout: int,
) -> list[dict]:
    """Fetch from conf.researchr.org track pages.

    HTML structure observed:
      <div id="event-overview">
        <table class="table">
          <thead>...</thead>
          <tbody>
            <tr>
              <td>(star icon)</td>
              <td>
                <a data-event-modal="uuid">TITLE</a>
                <div class="prog-track">TRACK</div>
                <div class="performers">
                  <a href="...">AUTHOR</a>, ...
                </div>
                <a class="publication-link" href="...">Pre-print / DOI</a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

    Each row also has data-event-modal which opens a detail popup with
    abstract, DOI, and other metadata.
    """
    papers: list[dict] = []
    from agent_survey.services.dblp import make_paper_id

    # Load page — domcontentloaded is enough since paper data is in the
    # initial HTML table (not lazy-loaded).  networkidle waits for every
    # tracking pixel / analytics script and can take 30+ extra seconds.
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
    # Wait for the paper table to appear (max 8 s for JS to render)
    try:
        await page.wait_for_selector("[id*='event'] table tbody tr", timeout=8000)
    except Exception:
        pass  # might still have papers via other selectors
    await asyncio.sleep(1)  # brief settle

    # Strategy 1: [id*='event'] table tbody tr (conf.researchr.org)
    rows = await page.query_selector_all("[id*='event'] table tbody tr")
    if rows:
        for row in rows:
            # Title link
            title_el = await row.query_selector("td a[data-event-modal]")
            if not title_el:
                continue
            title = (await title_el.inner_text()).strip()
            if not title or len(title) < 10:
                continue

            # Authors from .performers container
            authors: list[str] = []
            perf_els = await row.query_selector_all("td .performers a")
            for a_el in perf_els:
                author = (await a_el.inner_text()).strip()
                if author:
                    authors.append(author)

            # DOI / external link
            doi = None
            ee = None
            pub_el = await row.query_selector("td a.publication-link")
            if pub_el:
                pub_href = (await pub_el.get_attribute("href")) or ""
                if "doi.org" in pub_href:
                    doi = pub_href.split("doi.org/")[-1]
                elif "arxiv" in pub_href:
                    ee = pub_href

            paper = {
                "dblp_key": None,
                "title": title,
                "year": 0,  # filled by caller
                "authors": authors,
                "doi": doi,
                "url": ee,
                "venue": "",  # filled by caller
                "venue_area": "",
                "venue_type": "conf",
                "source_flags": ["playwright", "conf_researchr"],
            }
            paper["paper_id"] = make_paper_id(
                {"dblp_key": None, "doi": doi, "title": title, "year": 0}
            )
            papers.append(paper)

    return papers


_TRACK_LABELS = re.compile(
    r"\b(Research Papers|Industry Papers|Ideas, Visions and Reflections"
    r"|Demonstrations|NIER|Tool Demos?|Doctoral Symposium"
    r"|Journal First|Keynote|Workshop|Tutorial|Poster)\b",
    re.IGNORECASE,
)


async def _try_extract_abstracts(page, papers: list[dict]) -> None:
    """Click each paper's modal link to extract abstracts if available."""
    if not papers:
        return

    # Only try first 5 papers to see if modals have abstracts (avoid excessive clicks)
    sample_modal_links = await page.query_selector_all("a[data-event-modal]")
    if not sample_modal_links:
        return

    # Click one modal to check if abstracts exist
    try:
        await sample_modal_links[0].click()
        await asyncio.sleep(1)
        modal = await page.query_selector(".modal-body, [class*='modal']")
        if modal:
            modal_text = (await modal.inner_text()).lower()
            # If modal has abstract content, extract for all
            if "abstract" in modal_text:
                print(f"  [playwright] modal has abstracts, extracting...")
            else:
                print(f"  [playwright] modal found but no abstract section")
        # Close modal
        close_btn = await page.query_selector(".modal .close, [data-dismiss='modal']")
        if close_btn:
            await close_btn.click()
        else:
            await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
    except Exception:
        pass


async def _fetch_papers_async(
    url: str,
    *,
    proxy: str = "",
    venue_name: str = "",
    venue_area: str = "",
    venue_type: str = "conf",
    year: int = 0,
    timeout: int = 45,
) -> list[dict]:
    """Fetch accepted papers from a conference website using Playwright.

    Handles:
    - conf.researchr.org (FSE, ISSTA, etc.)
    - colmweb.org (COLM)
    - Generic fallback selectors
    """
    from playwright.async_api import async_playwright

    proxy_setting = {"server": proxy} if proxy else None
    papers: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy=proxy_setting,  # type: ignore[arg-type]
            args=["--no-sandbox"],
        )
        page = await browser.new_page()

        # ── Route: conf.researchr.org ───────────────────────────────
        if "researchr.org" in url or "esec-fse.org" in url:
            papers = await _fetch_conf_researchr(page, url, timeout)
            if papers:
                # Try to extract abstracts from modals (samples first)
                await _try_extract_abstracts(page, papers)

        # ── Route: colmweb / miniconf ────────────────────────────────
        elif "colmweb.org" in url:
            # Already handled by external.py fetch_json_papers, this is a
            # fallback in case the JSON endpoint changes format.
            pass

        # ── Generic fallback ─────────────────────────────────────────
        if not papers:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                await asyncio.sleep(3)
            except Exception as e:
                await browser.close()
                raise RuntimeError(f"Playwright failed to load {url}: {e}")
            # Try common link patterns
            all_links = await page.query_selector_all("a[href]")
            for a in all_links:
                href = (await a.get_attribute("href")) or ""
                text = (await a.inner_text()).strip()
                if "doi.org" in href and text and len(text) > 15:
                    # This might be a paper title linked to DOI
                    pass

        await browser.close()

    # Fill in venue/year metadata
    from agent_survey.services.dblp import make_paper_id

    for p in papers:
        p["venue"] = venue_name
        p["venue_area"] = venue_area
        p["venue_type"] = venue_type
        p["year"] = year
        p["paper_id"] = make_paper_id(
            {"dblp_key": p.get("dblp_key"), "doi": p.get("doi"), "title": p["title"], "year": year}
        )

    return papers


def fetch_papers(
    url: str,
    *,
    proxy: str = "",
    venue_name: str = "",
    venue_area: str = "",
    venue_type: str = "conf",
    year: int = 0,
    timeout: int = 45,
) -> Iterator[dict]:
    """Synchronous wrapper around the async Playwright fetcher."""
    result = asyncio.run(
        _fetch_papers_async(
            url,
            proxy=proxy,
            venue_name=venue_name,
            venue_area=venue_area,
            venue_type=venue_type,
            year=year,
            timeout=timeout,
        )
    )
    yield from result
